from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware  # 1. 미들웨어 불러오기
from schemas import RouteRequest, RouteResponse
from services.maps import get_tmap_route_info

app = FastAPI(title="Navigation Engine")

# 2. CORS 설정 추가 (브라우저 차단 해제)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],      # 모든 곳에서 접속 허용
    allow_credentials=True,
    allow_methods=["*"],      # GET, POST 등 모든 방식 허용
    allow_headers=["*"],      # 모든 헤더 허용
)

@app.get("/")
async def root():
    return {"message": "서버가 정상적으로 작동 중입니다."}

@app.post("/get-route", response_model=RouteResponse)
async def get_route(request: RouteRequest):
    route_data = await get_tmap_route_info(
        request.start_lat, request.start_lon, 
        request.end_lat, request.end_lon
    )
    
    if not route_data:
        raise HTTPException(status_code=500, detail="Tmap API 응답 오류")
    
    return RouteResponse(
        total_time_seconds=route_data['time'],
        total_time_minutes=round(route_data['time'] / 60, 1),
        total_distance_meters=route_data['distance'],
        path=route_data['path'],
        message="성공적으로 경로를 가져왔습니다."
    )