"""
main.py — KTAS 응급 중증도 분류 FastAPI 서빙
실행: uvicorn main:app --reload --port 8000
threshold_config.json에서 동적로드(THRESHOLD_K4, THRESHOLD_K5)

"""
import os
import json
import re
import logging
import numpy as np
import torch
from typing import Optional
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from model_loader import load_model

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)
# threshold_config.json에서 동적로드
# ── threshold_config.json에서 동적 로드 ──────────────────
_THRESHOLD_CONFIG_PATH = "./ktas_ai_model/threshold_config.json"

def _load_thresholds() -> tuple[float, float]:
    if os.path.exists(_THRESHOLD_CONFIG_PATH):
        with open(_THRESHOLD_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        k4 = cfg.get("threshold_k4") or cfg.get("THRESHOLD_K4", 0.86)
        k5 = cfg.get("threshold_k5") or cfg.get("THRESHOLD_K5", 0.72)
        logger.info(f"threshold 로드: K4={k4} / K5={k5} (from {_THRESHOLD_CONFIG_PATH})")
        return float(k4), float(k5)
    logger.warning("threshold_config.json 없음 → fallback 사용: K4=0.86 / K5=0.72")
    return 0.86, 0.72

THRESHOLD_K4, THRESHOLD_K5 = _load_thresholds()

KTAS_LABELS = ["KTAS1", "KTAS2", "KTAS3", "KTAS4", "KTAS5"]

# KTAS 공급자 매뉴얼(대한응급의학회, 2019) 약어 섹션 및 1차 고려사항 기준
# 수록 항목: 의식(GCS), 혈역학적 상태(BP, HR), 호흡(RR, SpO2), 통증(NRS),
#            소생술(CPR), 소아 의식 평가 대안(AVPU)
# → 해당 약어를 한국어로 치환하여 모델 입력 품질 및 한글 비율 계산 신뢰도 향상
ABBR_MAP = {
    'CPR':  '심폐소생술',
    'SpO2': '산소포화도',
    'GCS':  '의식수준',
    'NRS':  '통증점수',
    'BP':   '혈압',
    'HR':   '심박수',
    'RR':   '호흡수',
    'AVPU': '의식수준',
}
# 단어 경계(\b) 기반 치환, 대소문자 구분 없이 매칭
ABBR_RE = re.compile(
    r'\b(' + '|'.join(re.escape(k) for k in ABBR_MAP) + r')\b',
    re.IGNORECASE
)


# 앱 초기화 & 모델 로드
app = FastAPI(
    title="KTAS 응급 중증도 분류 API",
    description="환자 증상 텍스트 → KTAS 1~5 등급 분류 (임상 데이터 기반 보수적 예측)",
    version="1.0.0"
)

model, tokenizer, device = load_model()
logger.info(f"모델 로드 완료 | device: {device}")


# ── 요청 / 응답 스키마 ────────────────────────────────────────────────────────
class SymptomRequest(BaseModel):
    symptom_text: str


class PredictResponse(BaseModel):
    ktas_level:      int
    is_emergency:    bool           # ktas_level <= 3 → True (권역응급센터 라우팅)
    confidence:      float          # 최종 예측 등급의 softmax 확률
    original_level: Optional[int] = None
    original_confidence: Optional[float] = None
    adjusted:        bool           # 보수적 상향 조정 여부
    adjusted_reason: Optional[str] = None     # 조정 사유 (None이면 미조정)
    probabilities:   dict  # KTAS1~5 전체 확률 분포
    highlight_keywords: list[str]   # ["가슴", "통증", "호흡"] 형태로 반환


# ── 입력 검증 & 정제 ──────────────────────────────────────────────────────────
def validate_and_clean(text: str) -> str:
    text = text.strip()

    if not text:
        raise HTTPException(status_code=422, detail="증상 텍스트를 입력해 주세요.")
    if len(text) > 200:
        raise HTTPException(status_code=422, detail="200자 이내로 입력해 주세요.")

    # 반복 문자 정제: "아아아아파요" → "아아파요"
    text = re.sub(r'(.)\1{2,}', r'\1\1', text)

    # KTAS 가이드라인 약어를 한국어로 치환 (모델 입력 품질 향상 + 한글 비율 정상화)
    # 예) "CPR 중입니다" → "심폐소생술 중입니다"
    text = ABBR_RE.sub(lambda m: ABBR_MAP[m.group().upper()], text)

    hangul_chars = re.findall(r'[\uAC00-\uD7A3]', text)
    if len(hangul_chars) < 2:
        raise HTTPException(status_code=422, detail="정확한 증상을 한국어로 입력해 주세요.")

    # 순수 글자 추출 (공백 및 일반적인 특수문자, 자음/모음 단독 사용 등 제외)
    pure_text = re.sub(
        r'[\s\.,!\?~@#\$%\^&\*\(\)_\+\-\=\[\]\{\}\|;:\'\"<>/\u3131-\u314E\u314F-\u3163]',
        '', text
    )
    if len(pure_text) > 0:
        hangul_ratio = len(hangul_chars) / len(pure_text)
        if hangul_ratio < 0.5:
            raise HTTPException(status_code=422, detail="의미 없는 문자가 너무 많습니다. 한글 증상 위주로 정확히 입력해 주세요.")

    return text


# 보수적 상향 조정 로직
def apply_conservative_threshold(pred: int, probs: np.ndarray):
    if pred == 4 and probs[4] < THRESHOLD_K5:
        reason = (
            f"K5 확신도({probs[4]:.3f}) < 임계치({THRESHOLD_K5}) → K4 상향"
        )
        return 3, True, reason

    if pred == 3 and probs[3] < THRESHOLD_K4:
        reason = (
            f"K4 확신도({probs[3]:.3f}) < 임계치({THRESHOLD_K4}) → K3 상향"
        )
        return 2, True, reason

    return pred, False, None

# 예측 엔드포인트
@app.post("/predict", response_model=PredictResponse)
def predict(req: SymptomRequest):
    text = validate_and_clean(req.symptom_text)
    logger.info(f"입력: '{text[:60]}{'...' if len(text) > 60 else ''}'")

    try:
        encoding = tokenizer(
            text,
            add_special_tokens=True,
            max_length=180,
            padding='max_length',
            truncation=True,
            return_tensors='pt'
        )
        # encoding 언패킹: token_type_ids 등 모든 토크나이저 출력을 자동 포함
        inputs = {k: v.to(device) for k, v in encoding.items()}

        with torch.no_grad():
            output = model(**inputs, output_attentions=True)
            logits = output.logits

            last_layer_attn = output.attentions[-1]  # (1, 12, 180, 180)
            cls_attn = last_layer_attn[0, :, 0, :].mean(dim=0).cpu().numpy()  # (180,)

            # 2. 토큰 ID를 텍스트 토큰으로 복원
            input_ids_list = inputs["input_ids"][0].tolist()
            tokens = tokenizer.convert_ids_to_tokens(input_ids_list)

            # 3. 특수 토큰 제외 및 서브워드(##) 결합 처리
            word_scores = []
            current_word = ""
            current_score = 0.0
            subword_count = 0

            for tok, score in zip(tokens, cls_attn):
                if tok in ["[CLS]", "[SEP]", "[PAD]"]:
                    continue

                if tok.startswith("##"):
                    current_word += tok.replace("##", "")
                    current_score += score
                    subword_count += 1
                else:
                    if current_word:
                        # 이전 단어의 평균 어텐션 점수 저장
                        word_scores.append((current_word, current_score / (subword_count + 1)))
                    current_word = tok
                    current_score = score
                    subword_count = 0
            if current_word:
                word_scores.append((current_word, current_score / (subword_count + 1)))

            # 4. 조사 및 1글자짜리 노이즈 필터링 후, 상위 25% 중요 키워드 추출
            meaningful_words = [ws for ws in word_scores if len(ws[0]) > 1]
            if meaningful_words:
                scores_only = [ws[1] for ws in meaningful_words]
                threshold_val = np.percentile(scores_only, 75)  # 상위 25% 컷오프
                extracted_keywords = [ws[0] for ws in meaningful_words if ws[1] >= threshold_val]
            else:
                extracted_keywords = []

            # 5. 의료 약어 역매핑 (프론트엔드 원본 텍스트 매칭용 안전장치)
            # 예: "심폐소생술"이 중요 단어로 뽑혔는데 원본에 "CPR"이 있으면 "CPR"도 형광펜 대상에 추가
            REVERSE_ABBR_MAP = {v: k for k, v in ABBR_MAP.items()}
            final_keywords = []
            for kw in extracted_keywords:
                final_keywords.append(kw)
                if kw in REVERSE_ABBR_MAP:
                    final_keywords.append(REVERSE_ABBR_MAP[kw])

            # 중복 제거
            final_keywords = list(set(final_keywords))

        probs         = torch.softmax(logits, dim=-1).squeeze().cpu().numpy()
        original_pred = int(np.argmax(probs))   # 0-indexed (K1=0 ~ K5=4)

        # 보수적 상향 조정
        pred, adjusted, adjusted_reason = apply_conservative_threshold(
            original_pred, probs
        )

        ktas_level   = pred + 1                  # 1-indexed 반환
        is_emergency = ktas_level <= 3

        prob_dict = {KTAS_LABELS[i]: round(float(probs[i]), 4) for i in range(5)}

        # 조정된 경우에만 원본 예측값 기록 (디버깅 및 백엔드 투명성)
        original_level_out      = (original_pred + 1) if adjusted else None
        original_confidence_out = round(float(probs[original_pred]), 4) if adjusted else None

        logger.info(
            f"결과: KTAS {ktas_level} | 응급: {is_emergency} | "
            f"확신도: {probs[pred]:.3f} | 조정: {adjusted}"
        )

        return PredictResponse(
            ktas_level=ktas_level,
            is_emergency=is_emergency,
            confidence=round(float(probs[pred]), 4),
            original_level=original_level_out,
            original_confidence=original_confidence_out,
            adjusted=adjusted,
            adjusted_reason=adjusted_reason,
            probabilities=prob_dict,
            highlight_keywords=final_keywords
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"예측 오류: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="서버 내부 오류가 발생했습니다.")


# 헬스체크 엔드포인트
@app.get("/health")
def health():
    return {
        "status":       "ok",
        "model":        "klue/bert-base (KTAS fine-tuned)",
        "threshold_k4": THRESHOLD_K4,
        "threshold_k5": THRESHOLD_K5,
    }