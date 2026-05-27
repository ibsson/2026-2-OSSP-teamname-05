import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL_PATH = "./ktas_ai_model/"


def load_model():
    """
    파인튜닝된 KTAS 분류 모델을 로드하고 (model, tokenizer, device)를 반환.
    FastAPI 앱 시작 시 1회만 호출하여 전역에서 재사용.
    """
    if torch.cuda.is_available():
        device = torch.device("cuda")
    elif torch.backends.mps.is_available():
        device = torch.device("mps")
    else:
        device = torch.device("cpu")

    tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
    model     = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH)
    model.to(device)
    model.eval()

    return model, tokenizer, device