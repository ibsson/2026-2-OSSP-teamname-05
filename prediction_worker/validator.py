from datetime import datetime, timedelta

import pandas as pd
from db import append_table, read_table_from_postgres, delete_rows_by_ids


VALIDATION_TOLERANCE_MINUTES = 8


def read_table(table_name):
    return read_table_from_postgres(table_name)


def delete_validated_pending(prediction_ids):
    delete_rows_by_ids(
        table_name="pending_multihorizon_predictions",
        id_column="prediction_id",
        ids=prediction_ids,
    )


def find_actual_bed_for_prediction(history_df, hospital_id, target_time):
    """
    특정 병원의 target_time과 가장 가까운 실제 병상 수를 찾는다.
    수집 주기가 10분이므로 target_time 기준 ±8분 안에서 가장 가까운 값을 사용.
    """
    hospital_history = history_df[history_df["hpid"].astype(str) == str(hospital_id)].copy()

    if hospital_history.empty:
        return None, None

    hospital_history["time_diff"] = (
        hospital_history["log_time"] - target_time
    ).abs()

    nearest = hospital_history.sort_values("time_diff").iloc[0]

    if nearest["time_diff"] > timedelta(minutes=VALIDATION_TOLERANCE_MINUTES):
        return None, None

    actual_time = nearest["log_time"]
    actual_beds = pd.to_numeric(nearest["hvec"], errors="coerce")

    if pd.isna(actual_beds):
        return None, None

    return actual_time, float(actual_beds)


def validate_pending_predictions():
    print("\n4. 예측 결과 검증")

    pending_df = read_table("pending_multihorizon_predictions")
    history_df = read_table("realtime_bed_history")

    if pending_df.empty:
        print("검증할 pending 예측이 없습니다.")
        return pd.DataFrame()

    if history_df.empty:
        print("실제 병상 이력이 없습니다.")
        return pd.DataFrame()

    pending_df["target_time"] = pd.to_datetime(pending_df["target_time"], errors="coerce")
    pending_df["created_at"] = pd.to_datetime(pending_df["created_at"], errors="coerce")
    history_df["log_time"] = pd.to_datetime(history_df["log_time"], errors="coerce")

    now = datetime.now()

    # target_time이 아직 안 된 예측은 검증하지 않음
    due_df = pending_df[pending_df["target_time"] <= now].copy()

    if due_df.empty:
        print("아직 target_time에 도달한 pending 예측이 없습니다.")
        return pd.DataFrame()

    validation_rows = []
    validated_ids = []

    for _, row in due_df.iterrows():
        prediction_id = row["prediction_id"]
        hospital_id = row["hospital_id"]
        target_time = row["target_time"]

        actual_time, actual_beds = find_actual_bed_for_prediction(
            history_df=history_df,
            hospital_id=hospital_id,
            target_time=target_time
        )

        if actual_time is None:
            continue

        predicted_beds = pd.to_numeric(row["predicted_beds"], errors="coerce")
        current_available_beds = pd.to_numeric(row["current_available_beds"], errors="coerce")

        if pd.isna(predicted_beds):
            continue

        count_error = float(predicted_beds) - float(actual_beds)
        abs_error = abs(count_error)

        pred_exist = 1 if float(predicted_beds) > 0 else 0
        actual_exist = 1 if float(actual_beds) > 0 else 0
        exist_correct = 1 if pred_exist == actual_exist else 0

        validation_rows.append({
            "prediction_id": prediction_id,
            "created_at": row["created_at"],
            "target_time": target_time,
            "actual_time": actual_time,
            "horizon_minutes": int(row["horizon_minutes"]),
            "horizon": row["horizon"],
            "hospital_id": hospital_id,
            "hospital_name": row["hospital_name"],
            "district": row["district"],
            "current_available_beds": current_available_beds,
            "predicted_beds": float(predicted_beds),
            "actual_beds": float(actual_beds),
            "count_error": count_error,
            "abs_error": abs_error,
            "pred_exist": pred_exist,
            "actual_exist": actual_exist,
            "exist_correct": exist_correct,
        })

        validated_ids.append(prediction_id)

    if not validation_rows:
        print("검증 가능한 예측이 아직 없습니다.")
        return pd.DataFrame()

    result_df = pd.DataFrame(validation_rows)

    append_table(result_df, "multihorizon_validation_results")
    delete_validated_pending(validated_ids)

    print("검증 결과 저장 완료")
    print("검증 행 수:", len(result_df))

    print("\n검증 요약")
    summary = result_df.groupby("horizon_minutes").agg(
        count=("prediction_id", "count"),
        mae=("abs_error", "mean"),
        exist_accuracy=("exist_correct", "mean")
    ).reset_index()

    print(summary.to_string(index=False))

    return result_df