from pydantic import BaseModel
from typing import List, Optional

class RouteRequest(BaseModel):
    # 반드시 변수명 뒤에 콜론(:)을 써야 합니다! (= 금지)
    start_lat: float
    start_lon: float
    end_lat: float
    end_lon: float

class RouteResponse(BaseModel):
    total_time_seconds: int
    total_time_minutes: float
    total_distance_meters: int
    # List[List[float]] 대신 아래처럼 써도 됩니다.
    path: List[List[float]] 
    message: str

# Pydantic이 모델을 강제로 다시 그리게 해서 에러를 방지합니다.
RouteResponse.model_rebuild()