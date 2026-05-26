import os
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

import pandas as pd
import requests

from config import (
    BASE_URL,
    DATA_DIR,
    EMERGENCY_API_KEY,
    HISTORY_KEEP_MINUTES,
    HISTORY_PATH,
)
from db import replace_table


def parse_int(value):
    try:
        return int(str(value).strip())
    except Exception:
        return None


def read_csv_auto(path):
    encodings = ["utf-8-sig", "cp949", "euc-kr", "utf-8"]
    last_error = None

    for enc in encodings:
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError as e:
            last_error = e

    raise last_error


def collect_realtime_beds_once():
    """
    공공데이터 API에서 서울특별시 실시간 응급실 병상 정보를 1회 수집한다.
    """
    if not EMERGENCY_API_KEY:
        raise ValueError(".env 파일에 EMERGENCY_API_KEY가 없습니다.")

    params = {
        "serviceKey": EMERGENCY_API_KEY,
        "STAGE1": "서울특별시",
        "pageNo": 1,
        "numOfRows": 300,
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=15)
    except requests.RequestException as e:
        print("API 요청 실패:", e)
        return pd.DataFrame()

    if response.status_code == 429:
        print("429 요청 제한 발생. 이번 수집은 건너뜁니다.")
        return pd.DataFrame()

    if response.status_code != 200:
        print("HTTP 오류:", response.status_code)
        print(response.text[:300])
        return pd.DataFrame()

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as e:
        print("XML 파싱 오류:", e)
        print(response.text[:300])
        return pd.DataFrame()

    result_code = root.findtext(".//resultCode")
    result_msg = root.findtext(".//resultMsg")

    if result_code != "00":
        print("API 응답 오류:", result_code, result_msg)
        return pd.DataFrame()

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []

    for item in root.findall(".//item"):
        hpid = item.findtext("hpid")
        duty_name = item.findtext("dutyName")

        if not hpid or not duty_name:
            continue

        rows.append({
            "log_time": now,
            "hpid": hpid,
            "duty_name": duty_name,
            "hvec": parse_int(item.findtext("hvec")),
            "hvicc": parse_int(item.findtext("hvicc")),
            "hv28": parse_int(item.findtext("hv28")),
            "hv29": parse_int(item.findtext("hv29")),
            "hv30": parse_int(item.findtext("hv30")),
            "hv27": parse_int(item.findtext("hv27")),
            "hvidate": item.findtext("hvidate"),
        })

    df = pd.DataFrame(rows)

    print("API 수집 완료")
    print("이번 수집 행 수:", len(df))

    if not df.empty:
        print("이번 수집 병원 수:", df["hpid"].nunique())

    return df


def append_realtime_history(new_df: pd.DataFrame):
    """
    새 수집 데이터를 기존 이력에 추가한 뒤,
    최근 HISTORY_KEEP_MINUTES분 데이터만 유지한다.
    """
    os.makedirs(DATA_DIR, exist_ok=True)

    if new_df is None or new_df.empty:
        print("저장할 실시간 데이터가 없습니다.")
        return pd.DataFrame()

    if os.path.exists(HISTORY_PATH):
        old_df = read_csv_auto(HISTORY_PATH)
        combined = pd.concat([old_df, new_df], ignore_index=True)
    else:
        combined = new_df.copy()

    combined["log_time"] = pd.to_datetime(combined["log_time"], errors="coerce")

    cutoff = datetime.now() - timedelta(minutes=HISTORY_KEEP_MINUTES)
    combined = combined[combined["log_time"] >= cutoff].copy()

    combined = combined.drop_duplicates(
        subset=["log_time", "hpid"],
        keep="last",
    )

    combined = combined.sort_values(["hpid", "log_time"]).reset_index(drop=True)

    combined.to_csv(HISTORY_PATH, index=False, encoding="utf-8-sig")

    # Supabase에는 최근 3시간 20분 이력만 유지
    replace_table(combined, "realtime_bed_history")

    print("실시간 병상 이력 저장 완료:", HISTORY_PATH)
    print("최근 이력 크기:", combined.shape)
    print("최근 이력 병원 수:", combined["hpid"].nunique())

    return combined
