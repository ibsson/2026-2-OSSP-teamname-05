import os
import json
from datetime import datetime, timedelta
from weather_api import get_weather_features_by_hospital, get_weather_for_hospital

import joblib
import numpy as np
import pandas as pd
import torch
import torch.nn as nn

from config import (
    SEQ_LEN,
    HORIZONS,
    HISTORY_PATH,
    MODEL_PATH,
    X_SCALER_PATH,
    Y_SCALER_PATH,
    FEATURE_COLS_PATH,
    TARGET_COLS_PATH,
    HOSPITAL_DISTRICT_PATH,
    DATA_DIR,
)
from db import replace_table, append_table


class MultiHorizonGRU(nn.Module):
    def __init__(self, input_size, hidden_size=128, num_layers=2, output_size=9, dropout=0.2):
        super().__init__()

        self.gru = nn.GRU(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout
        )

        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, output_size)
        )

    def forward(self, x):
        out, _ = self.gru(x)
        last_hidden = out[:, -1, :]
        pred = self.fc(last_hidden)
        return pred


def read_csv_auto(path):
    encodings = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]
    last_error = None

    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError as e:
            last_error = e

    raise last_error


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_model_and_scalers():
    feature_cols = load_json(FEATURE_COLS_PATH)
    target_cols = load_json(TARGET_COLS_PATH)

    x_scaler = joblib.load(X_SCALER_PATH)
    y_scaler = joblib.load(Y_SCALER_PATH)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model = MultiHorizonGRU(
        input_size=len(feature_cols),
        hidden_size=128,
        num_layers=2,
        output_size=len(target_cols),
        dropout=0.2
    ).to(device)

    state_dict = torch.load(MODEL_PATH, map_location=device)
    model.load_state_dict(state_dict)
    model.eval()

    print("90분 GRU 모델 로드 완료")
    print("device:", device)
    print("feature 개수:", len(feature_cols))
    print("target 개수:", len(target_cols))

    return model, x_scaler, y_scaler, feature_cols, target_cols, device


def safe_numeric(series):
    return pd.to_numeric(series, errors="coerce")


def load_hospital_district_map():
    if not os.path.exists(HOSPITAL_DISTRICT_PATH):
        print(f"병원 구 매핑 파일이 없습니다: {HOSPITAL_DISTRICT_PATH}")
        return {}

    district_df = read_csv_auto(HOSPITAL_DISTRICT_PATH)

    if "hpid" not in district_df.columns or "district" not in district_df.columns:
        print("hospital_districts.csv에는 hpid, district 컬럼이 필요합니다.")
        return {}

    district_df["hpid"] = district_df["hpid"].astype(str)
    district_df["district"] = district_df["district"].astype(str)

    return dict(zip(district_df["hpid"], district_df["district"]))


def apply_district_and_weather_features(df):
    district_map = load_hospital_district_map()
    df["district"] = df["hpid"].astype(str).map(district_map).fillna("")

    weather_map = get_weather_features_by_hospital()

    weather_rows = []

    for _, row in df.iterrows():
        weather = get_weather_for_hospital(row["hpid"], weather_map)

        weather_rows.append({
            "temperature": weather["temperature"],
            "rainfall": weather["rainfall"],
            "snowfall": weather["snowfall"],
            "is_rain": weather["is_rain"],
            "is_snow": weather["is_snow"],
        })

    weather_df = pd.DataFrame(weather_rows, index=df.index)

    for col in ["temperature", "rainfall", "snowfall", "is_rain", "is_snow"]:
        df[col] = weather_df[col]

    return df

def make_prediction_features(history_df):
    """
    realtime_bed_history를 학습 데이터의 feature 구조와 비슷하게 변환한다.

    현재 API에서 사용하는 주 병상 수는 hvec로 둔다.
    hvec = 응급실 일반 병상 가용 수로 사용.
    """
    df = history_df.copy()

    df["log_time"] = pd.to_datetime(df["log_time"], errors="coerce")
    df = df.dropna(subset=["log_time", "hpid"]).copy()

    numeric_cols = ["hvec", "hvicc", "hv28", "hv29", "hv30", "hv27"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = safe_numeric(df[col])

    df["available_beds"] = safe_numeric(df["hvec"]).fillna(0)

    df = df.sort_values(["hpid", "log_time"]).reset_index(drop=True)

    # 병상 감소량: 이전보다 줄어든 병상 수만 양수로 계산
    df["prev_available_beds"] = df.groupby("hpid")["available_beds"].shift(1)
    df["diff_beds"] = df["prev_available_beds"] - df["available_beds"]
    df["decrease_last_10min"] = df["diff_beds"].clip(lower=0).fillna(0)

    # rolling feature
    def rolling_sum_by_hospital(window):
        return (
            df.groupby("hpid")["decrease_last_10min"]
            .rolling(window=window, min_periods=1)
            .sum()
            .reset_index(level=0, drop=True)
        )

    df["decrease_last_30min"] = rolling_sum_by_hospital(3)
    df["decrease_last_1h"] = rolling_sum_by_hospital(6)
    df["decrease_last_3h"] = rolling_sum_by_hospital(18)

    df["decrease_rate_30min"] = df["decrease_last_30min"] / 3
    df["decrease_rate_1h"] = df["decrease_last_1h"] / 6
    df["decrease_rate_3h"] = df["decrease_last_3h"] / 18

    df["is_overcrowded"] = (df["available_beds"] <= 2).astype(int)

    def overcrowd_level(x):
        if x <= 0:
            return 3
        if x <= 2:
            return 2
        if x <= 5:
            return 1
        return 0

    df["overcrowd_level"] = df["available_beds"].apply(overcrowd_level)

    df["hour"] = df["log_time"].dt.hour
    df["weekday"] = df["log_time"].dt.weekday
    df["is_weekend"] = (df["weekday"] >= 5).astype(int)
    df["month"] = df["log_time"].dt.month

    # ============================================================
    # 수요 점수 feature
    # 현재 실시간 worker에는 학습 당시 사용한 demand score 테이블을 붙이지 않으므로
    # 기본값 1.0으로 둔다.
    # ============================================================

    df["hour_demand_score"] = 1.0
    df["weekday_demand_score"] = 1.0
    df["month_demand_score"] = 1.0
    df["season_demand_score"] = 1.0
    df["district_demand_score"] = 1.0

    # ============================================================
    # 병원별 격자 예보 날씨 feature 적용
    # ============================================================

    df = apply_district_and_weather_features(df)

    return df


def build_sequences(feature_df, feature_cols):
    X_list = []
    meta_rows = []

    for hpid, group in feature_df.groupby("hpid"):
        group = group.sort_values("log_time").reset_index(drop=True)

        if len(group) < SEQ_LEN:
            continue

        latest_group = group.tail(SEQ_LEN).copy()

        X_seq = latest_group[feature_cols].values.astype(np.float32)

        latest_row = latest_group.iloc[-1]

        X_list.append(X_seq)
        meta_rows.append({
            "hospital_id": latest_row["hpid"],
            "hospital_name": latest_row.get("duty_name", ""),
            "district": latest_row.get("district", ""),
            "created_at": latest_row["log_time"],
            "current_available_beds": latest_row["available_beds"],
        })

    if not X_list:
        return np.empty((0, SEQ_LEN, len(feature_cols)), dtype=np.float32), pd.DataFrame()

    X = np.array(X_list, dtype=np.float32)
    meta = pd.DataFrame(meta_rows)

    return X, meta


def get_recommendation_status(current_beds, min_predicted_beds):
    if current_beds <= 0 or min_predicted_beds <= 0:
        return "병상 부족 위험"

    if current_beds <= 5 or min_predicted_beds < 3:
        return "주의 후보"

    return "추천 가능"


def make_pending_predictions(result_df):
    rows = []
    now = datetime.now()

    for _, row in result_df.iterrows():
        for h in HORIZONS:
            pred_col = f"pred_{h}min"
            target_time = now + timedelta(minutes=h)

            prediction_id = (
                f"{row['hospital_id']}_"
                f"{now.strftime('%Y%m%d%H%M%S')}_"
                f"{h}min"
            )

            rows.append({
                "prediction_id": prediction_id,
                "created_at": now.strftime("%Y-%m-%d %H:%M:%S"),
                "target_time": target_time.strftime("%Y-%m-%d %H:%M:%S"),
                "horizon_minutes": h,
                "horizon": f"{h}min",
                "hospital_id": row["hospital_id"],
                "hospital_name": row["hospital_name"],
                "district": row["district"],
                "current_available_beds": row["current_available_beds"],
                "predicted_beds": row[pred_col],
            })

    return pd.DataFrame(rows)


def run_prediction_90min():
    if not os.path.exists(HISTORY_PATH):
        print(f"실시간 병상 이력 파일이 없습니다: {HISTORY_PATH}")
        return pd.DataFrame(), pd.DataFrame()

    required_files = [
        MODEL_PATH,
        X_SCALER_PATH,
        Y_SCALER_PATH,
        FEATURE_COLS_PATH,
        TARGET_COLS_PATH,
    ]

    missing_files = [path for path in required_files if not os.path.exists(path)]
    if missing_files:
        print("모델 관련 파일이 없습니다.")
        for path in missing_files:
            print("-", path)
        return pd.DataFrame(), pd.DataFrame()

    history_df = read_csv_auto(HISTORY_PATH)
    print("이력 행 수:", len(history_df))
    print("병원 수:", history_df["hpid"].nunique() if not history_df.empty else 0)

    model, x_scaler, y_scaler, feature_cols, target_cols, device = load_model_and_scalers()

    feature_df = make_prediction_features(history_df)
    X, meta = build_sequences(feature_df, feature_cols)

    print("예측 가능 병원 수:", len(meta))

    if len(meta) == 0:
        print(f"아직 예측 가능한 병원이 없습니다. 병원별 최소 {SEQ_LEN}개 시점이 필요합니다.")
        return pd.DataFrame(), pd.DataFrame()

    n_features = X.shape[2]
    X_2d = X.reshape(-1, n_features)
    X_scaled = x_scaler.transform(X_2d).reshape(X.shape)

    X_tensor = torch.tensor(X_scaled, dtype=torch.float32).to(device)

    with torch.no_grad():
        pred_scaled = model(X_tensor).cpu().numpy()

    preds = y_scaler.inverse_transform(pred_scaled)

    result_df = meta.copy()

    for i, h in enumerate(HORIZONS):
        result_df[f"pred_{h}min"] = preds[:, i]

    pred_cols = [f"pred_{h}min" for h in HORIZONS]

    # 음수 예측은 0으로 보정
    for col in pred_cols:
        result_df[col] = result_df[col].clip(lower=0)

    result_df["min_predicted_beds_90min"] = result_df[pred_cols].min(axis=1)

    result_df["recommendation_status"] = result_df.apply(
        lambda row: get_recommendation_status(
            row["current_available_beds"],
            row["min_predicted_beds_90min"]
        ),
        axis=1
    )

    result_df["created_at"] = pd.to_datetime(result_df["created_at"]).dt.strftime("%Y-%m-%d %H:%M:%S")

    # 컬럼 순서 정리
    result_df = result_df[
        [
            "hospital_id",
            "hospital_name",
            "district",
            "created_at",
            "current_available_beds",
            "pred_10min",
            "pred_20min",
            "pred_30min",
            "pred_40min",
            "pred_50min",
            "pred_60min",
            "pred_70min",
            "pred_80min",
            "pred_90min",
            "min_predicted_beds_90min",
            "recommendation_status",
        ]
    ]

    pending_df = make_pending_predictions(result_df)

    os.makedirs(DATA_DIR, exist_ok=True)

    result_df.to_csv(
        os.path.join(DATA_DIR, "latest_multihorizon_predictions.csv"),
        index=False,
        encoding="utf-8-sig"
    )

    pending_df.to_csv(
        os.path.join(DATA_DIR, "pending_multihorizon_predictions.csv"),
        index=False,
        encoding="utf-8-sig"
    )

    replace_table(result_df, "latest_multihorizon_predictions")
    append_table(pending_df, "pending_multihorizon_predictions")

    print("90분 예측 저장 완료")
    print("latest 예측 행 수:", len(result_df))
    print("pending 예측 행 수:", len(pending_df))

    return result_df, pending_df