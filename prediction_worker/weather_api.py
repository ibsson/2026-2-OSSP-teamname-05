from datetime import datetime, timedelta
import os
import re

import numpy as np
import pandas as pd
import requests

from config import (
    KMA_API_KEY,
    KMA_FORECAST_GRID_URL,
    HOSPITAL_GRID_POINTS_PATH,
)


NX_SIZE = 149
NY_SIZE = 253


def get_default_weather_features():
    return {
        "temperature": 0.0,
        "rainfall": 0.0,
        "snowfall": 0.0,
        "is_rain": 0,
        "is_snow": 0,
    }


def get_latest_tmfc(now=None):
    """
    단기예보 발표시간:
    매일 02, 05, 08, 11, 14, 17, 20, 23시.
    """
    if now is None:
        now = datetime.now()

    forecast_hours = [2, 5, 8, 11, 14, 17, 20, 23]

    latest_hour = None
    for hour in forecast_hours:
        if now.hour >= hour:
            latest_hour = hour

    if latest_hour is None:
        prev_day = now - timedelta(days=1)
        return prev_day.strftime("%Y%m%d") + "23"

    return now.strftime("%Y%m%d") + f"{latest_hour:02d}"


def get_nearest_tmef(now=None):
    """
    병상 예측 시점과 가장 가까운 예보 발효시간 사용.
    일단 현재 시각 기준 다음 정시로 설정.
    """
    if now is None:
        now = datetime.now()

    if now.minute > 0:
        now = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    else:
        now = now.replace(second=0, microsecond=0)

    return now.strftime("%Y%m%d%H")


def parse_grid_values(text):
    """
    nph-dfs_shrt_grd 응답은 전국 격자값이 숫자 배열 형태로 내려온다.
    -99 계열 값은 결측으로 처리한다.
    """
    nums = []

    for token in re.split(r"[,\s]+", text):
        token = token.strip()

        if not token:
            continue

        try:
            value = float(token)
            nums.append(value)
        except ValueError:
            continue

    arr = np.array(nums, dtype=float)

    expected_size = NX_SIZE * NY_SIZE

    if len(arr) < expected_size:
        print(f"격자값 개수가 부족합니다. 받은 개수: {len(arr)}, 예상: {expected_size}")
        return None

    arr = arr[:expected_size]

    # x: 1~149, y: 1~253 기준으로 y행, x열 배열로 변환
    grid = arr.reshape((NY_SIZE, NX_SIZE))

    grid[grid <= -90] = np.nan

    return grid


def request_forecast_grid(var_name):
    """
    단기예보 격자자료에서 특정 변수 하나를 가져온다.
    사용 변수:
    - TMP: 기온
    - PTY: 강수형태
    """
    if not KMA_API_KEY or not KMA_FORECAST_GRID_URL:
        print("KMA_API_KEY 또는 KMA_FORECAST_GRID_URL이 없습니다. 날씨 기본값 사용.")
        return None

    params = {
        "tmfc": get_latest_tmfc(),
        "tmef": get_nearest_tmef(),
        "vars": var_name,
        "authKey": KMA_API_KEY,
    }

    print(f"기상청 단기예보 요청: var={var_name}, tmfc={params['tmfc']}, tmef={params['tmef']}")

    try:
        response = requests.get(KMA_FORECAST_GRID_URL, params=params, timeout=20)
    except requests.RequestException as e:
        print(f"기상청 {var_name} 요청 실패:", e)
        return None

    if response.status_code != 200:
        print(f"기상청 {var_name} HTTP 오류:", response.status_code)
        print(response.text[:500])
        return None

    grid = parse_grid_values(response.text)

    if grid is None:
        print(f"{var_name} 격자 파싱 실패")
        print(response.text[:500])

    return grid


def get_value_from_grid(grid, nx, ny, default=0.0):
    if grid is None:
        return default

    try:
        x = int(nx)
        y = int(ny)
    except Exception:
        return default

    # 기상청 격자는 1부터 시작, numpy index는 0부터 시작
    xi = x - 1
    yi = y - 1

    if yi < 0 or yi >= grid.shape[0] or xi < 0 or xi >= grid.shape[1]:
        return default

    value = grid[yi, xi]

    if np.isnan(value):
        return default

    return float(value)


def pty_to_flags(pty):
    """
    PTY 강수형태 기반 비/눈 여부.
    일반적으로:
    0 없음
    1 비
    2 비/눈
    3 눈
    4 소나기 또는 비 계열

    API별 세부코드 차이를 고려해 비/눈 여부만 보수적으로 처리.
    """
    try:
        p = int(round(float(pty)))
    except Exception:
        p = 0

    is_rain = 1 if p in [1, 2, 4, 5, 6] else 0
    is_snow = 1 if p in [2, 3, 6, 7] else 0

    return is_rain, is_snow


def load_hospital_grid_points():
    if not os.path.exists(HOSPITAL_GRID_POINTS_PATH):
        print(f"병원 격자 파일이 없습니다: {HOSPITAL_GRID_POINTS_PATH}")
        return pd.DataFrame()

    df = pd.read_csv(HOSPITAL_GRID_POINTS_PATH, encoding="utf-8-sig")

    needed_cols = ["hpid", "nx", "ny"]
    missing_cols = [col for col in needed_cols if col not in df.columns]

    if missing_cols:
        print(f"hospital_grid_points.csv에 필요한 컬럼이 없습니다: {missing_cols}")
        return pd.DataFrame()

    df["hpid"] = df["hpid"].astype(str)

    return df


def get_weather_features_by_hospital():
    """
    병원별 격자 좌표를 이용해 날씨 feature 생성.

    반환:
    {
        "A1100019": {
            "temperature": ...,
            "rainfall": 0.0,
            "snowfall": 0.0,
            "is_rain": ...,
            "is_snow": ...
        },
        ...
    }
    """
    hospital_df = load_hospital_grid_points()

    if hospital_df.empty:
        return {}

    print("기상청 단기예보 격자자료 요청 중...")

    temp_grid = request_forecast_grid("TMP")
    pty_grid = request_forecast_grid("PTY")

    result = {}

    for _, row in hospital_df.iterrows():
        hpid = str(row["hpid"])
        nx = row["nx"]
        ny = row["ny"]

        temperature = get_value_from_grid(temp_grid, nx, ny, default=0.0)
        pty = get_value_from_grid(pty_grid, nx, ny, default=0.0)

        is_rain, is_snow = pty_to_flags(pty)

        result[hpid] = {
            "temperature": temperature,
            "rainfall": 0.0,
            "snowfall": 0.0,
            "is_rain": is_rain,
            "is_snow": is_snow,
        }

    print("병원별 기상 feature 생성 완료")
    print("생성 병원 수:", len(result))

    return result


def get_weather_for_hospital(hpid, weather_map=None):
    if weather_map is None:
        weather_map = get_weather_features_by_hospital()

    return weather_map.get(str(hpid), get_default_weather_features())