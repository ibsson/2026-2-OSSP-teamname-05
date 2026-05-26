import os
from dotenv import load_dotenv

# 이 파일(config.py)이 있는 prediction_worker 폴더 기준으로 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# prediction_worker/.env를 명시적으로 로드
load_dotenv(os.path.join(BASE_DIR, ".env"))

# ============================================================
# 기본 설정
# ============================================================

COLLECT_INTERVAL_SECONDS = 600

# 모델 입력은 18개 시점 = 3시간
# API 수집 시간이 몇 분 밀릴 수 있으므로 3시간 20분 보관
HISTORY_KEEP_MINUTES = 200

SEQ_LEN = 18
HORIZONS = [10, 20, 30, 40, 50, 60, 70, 80, 90]

# ============================================================
# 경로 설정
# ============================================================

DATA_DIR = os.path.join(BASE_DIR, "data")
HISTORY_PATH = os.path.join(DATA_DIR, "realtime_bed_history.csv")

HOSPITAL_DISTRICT_PATH = os.path.join(DATA_DIR, "hospital_districts.csv")
HOSPITAL_GRID_POINTS_PATH = os.path.join(DATA_DIR, "hospital_grid_points.csv")

MODEL_DIR = os.path.join(BASE_DIR, "models")

MODEL_PATH = os.path.join(MODEL_DIR, "multihorizon_gru_90min.pt")
X_SCALER_PATH = os.path.join(MODEL_DIR, "x_scaler_multihorizon_90min.pkl")
Y_SCALER_PATH = os.path.join(MODEL_DIR, "y_scaler_multihorizon_90min.pkl")
FEATURE_COLS_PATH = os.path.join(MODEL_DIR, "multihorizon_feature_cols_90min.json")
TARGET_COLS_PATH = os.path.join(MODEL_DIR, "multihorizon_target_cols_90min.json")

# ============================================================
# 공공데이터 API
# ============================================================

EMERGENCY_API_KEY = os.getenv("EMERGENCY_API_KEY")

BASE_URL = (
    "http://apis.data.go.kr/B552657/ErmctInfoInqireService/"
    "getEmrrmRltmUsefulSckbdInfoInqire"
)

# ============================================================
# KMA Weather API
# ============================================================

KMA_API_KEY = os.getenv("KMA_API_KEY")

# 단기예보 격자자료 API
# .env 예:
# KMA_FORECAST_GRID_URL=https://apihub.kma.go.kr/api/typ01/cgi-bin/url/nph-dfs_shrt_grd
KMA_FORECAST_GRID_URL = os.getenv("KMA_FORECAST_GRID_URL")

# ============================================================
# PostgreSQL / Supabase
# ============================================================

POSTGRES_HOST = os.getenv("POSTGRES_HOST")
POSTGRES_PORT = os.getenv("POSTGRES_PORT")
POSTGRES_DB = os.getenv("POSTGRES_DB")
POSTGRES_USER = os.getenv("POSTGRES_USER")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")