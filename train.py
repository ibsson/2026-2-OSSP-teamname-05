import json
import numpy as np
import torch
from torch.utils.data import DataLoader, Subset
from transformers import AutoTokenizer, BertForSequenceClassification
from sklearn.metrics import classification_report, confusion_matrix
import pandas as pd

# ── 설정 ──────────────────────────────────────────────────
MODEL_DIR   = "./ktas_ai_model/"
SPLIT_PATH  = "./ktas_split.json"
DATA_PATH   = "./ktas_training_data_final.csv"
MAX_LEN     = 180
BATCH_SIZE  = 32
# calib 기준 목표 under-triage rate (buffer 확보용)
CALIB_TARGET_RATE = 0.027 # gap cnwjd ~2%p 감안

# ──────────────────────────────────────────────────────────

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# 데이터 로드
df = pd.read_csv(DATA_PATH)
texts  = df["symptom_text"].tolist()
labels = (df["ktas_level"] - 1).tolist()

with open(SPLIT_PATH) as f:
    split = json.load(f)
calib_idx = split["calib"]
test_idx  = split["test"]

tokenizer = AutoTokenizer.from_pretrained(MODEL_DIR)
model     = BertForSequenceClassification.from_pretrained(MODEL_DIR).to(device)
model.eval()

# ── Dataset ───────────────────────────────────────────────
class KTASDataset(torch.utils.data.Dataset):
    def __init__(self, texts, labels, tokenizer, max_len):
        enc = tokenizer(texts, padding="max_length", truncation=True,
                        max_length=max_len, return_tensors="pt")
        self.input_ids      = enc["input_ids"]
        self.attention_mask = enc["attention_mask"]
        self.token_type_ids = enc.get("token_type_ids",
                              torch.zeros_like(enc["input_ids"]))
        self.labels = torch.tensor(labels, dtype=torch.long)
    def __len__(self): return len(self.labels)
    def __getitem__(self, i):
        return {"input_ids": self.input_ids[i],
                "attention_mask": self.attention_mask[i],
                "token_type_ids": self.token_type_ids[i],
                "labels": self.labels[i]}

full_ds   = KTASDataset(texts, labels, tokenizer, MAX_LEN)
calib_ds  = Subset(full_ds, calib_idx)
test_ds   = Subset(full_ds, test_idx)

def collect_logits(ds):
    loader = DataLoader(ds, batch_size=BATCH_SIZE, shuffle=False)
    all_logits, all_labels = [], []
    with torch.no_grad():
        for batch in loader:
            logits = model(
                input_ids      = batch["input_ids"].to(device),
                attention_mask = batch["attention_mask"].to(device),
                token_type_ids = batch["token_type_ids"].to(device),
            ).logits
            all_logits.append(logits.cpu())
            all_labels.append(batch["labels"])
    return torch.cat(all_logits), torch.cat(all_labels)

print("calib logits 수집 중...")
calib_logits, calib_labels = collect_logits(calib_ds)
print("test logits 수집 중...")
test_logits,  test_labels  = collect_logits(test_ds)

# ── calib에서 K4 threshold 탐색 ───────────────────────────
# threashold_config.json 저장 값
TH_K5 = 0.74

def apply_thresholds(logits, th_k4, th_k5):
    probs = torch.softmax(logits, dim=-1).numpy()
    preds = probs.argmax(axis=1)
    # K5 보수적 상향 (K5 확신 < th_k5 → K4)
    k5_mask = (preds == 4) & (probs[:, 4] < th_k5)
    preds[k5_mask] = 3
    # K4 보수적 상향 (K4 확신 < th_k4 → K3)
    k4_mask = (preds == 3) & (probs[:, 3] < th_k4)
    preds[k4_mask] = 2
    return preds

def k3_under_rate(preds, labels_np):
    k3_mask = labels_np == 2          # 실제 K3
    under   = preds[k3_mask] > 2      # K4 또는 K5로 분류된 경우
    return under.sum(), under.mean()

calib_np = calib_labels.numpy()

print(f"\n[calib K4 threshold 탐색] 목표: K3 under-triage ≤ {CALIB_TARGET_RATE:.1%}")
print(f"{'TH_K4':>6} | {'under건수':>6} | {'under율':>7} | {'K4 Recall':>9}")
print("-" * 42)

best_th_k4 = None
for th in np.arange(0.50, 0.96, 0.01):
    th = round(float(th), 2)
    preds = apply_thresholds(calib_logits.clone(), th, TH_K5)
    n, rate = k3_under_rate(preds, calib_np)
    k4_mask = calib_np == 3
    k4_recall = (preds[k4_mask] == 3).mean() if k4_mask.sum() > 0 else 0.0
    marker = " ←" if rate <= CALIB_TARGET_RATE and best_th_k4 is None else ""
    print(f"{th:>6.2f} | {n:>6} | {rate:>7.2%} | {k4_recall:>9.4f}{marker}")
    if rate <= CALIB_TARGET_RATE and best_th_k4 is None:
        best_th_k4 = th

if best_th_k4 is None:
    print("\n[경고] calib에서 목표 달성 불가. CALIB_TARGET_RATE를 높이거나 재학습 필요.")
else:
    print(f"\n[선택] K4 threshold = {best_th_k4} (calib {CALIB_TARGET_RATE:.1%} 기준 최솟값)")

    # ── test 최종 평가 ──────────────────────────────────────
    test_np   = test_labels.numpy()
    test_pred = apply_thresholds(test_logits.clone(), best_th_k4, TH_K5)
    n_under, rate_under = k3_under_rate(test_pred, test_np)

    print(f"\n[TEST 결과] K4 threshold={best_th_k4} / K5 threshold={TH_K5}")
    print(f"K3 Under-triage = {n_under}건 ({rate_under:.2%}) | "
          f"ACS-COT = {'PASS' if rate_under <= 0.05 else 'FAIL'}")
    print(classification_report(test_np, test_pred,
                                 target_names=["K1","K2","K3","K4","K5"],
                                 digits=4))
    print(confusion_matrix(test_np, test_pred))

    # ── threshold_config.json 저장 ─────────────────────────
    config = {
        "threshold_k4": best_th_k4,
        "threshold_k5": TH_K5,
        "basis": (
            f"calib K3 under-triage ≤ {CALIB_TARGET_RATE:.1%} 기준으로 탐색. "
            f"calib→test gap 1.55%p 보정 적용. Epoch 6 모델 기준."
        ),
        "calib_target_rate": CALIB_TARGET_RATE,
        "epoch": 6,
    }
    config_path = MODEL_DIR + "threshold_config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)
    print(f"\n[저장] {config_path}")