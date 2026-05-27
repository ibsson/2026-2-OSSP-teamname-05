from flask import Flask, request, jsonify
from flask_cors import CORS
import requests
import xml.etree.ElementTree as ET
import json

app = Flask(__name__)
CORS(app)

SERVICE_KEY = "01da7e826b547a8ef3172722afdc5a9de6fab3fa2bd687b241245a59653eac08"

@app.route("/hospitals", methods=["GET"])
def get_hospitals():
    try:
        location_data = {}
        # 1. 병원 위치/이름/hpid 가져오기
        for page in range(1, 6):
            url = (
                "https://apis.data.go.kr/B552657/ErmctInfoInqireService/getEgytListInfoInqire"
                f"?serviceKey={SERVICE_KEY}"
                f"&pageNo={page}"
                "&numOfRows=50"
                "&Q0=서울특별시"
            )
            res = requests.get(url)
            res.encoding = "utf-8"
            root = ET.fromstring(res.text)
            for item in root.findall(".//item"):
                hpid = item.findtext("hpid")
                if hpid:
                    location_data[hpid.strip()] = {
                        "name": item.findtext("dutyName").strip(),
                        "lat": float(item.findtext("wgs84Lat")),
                        "lon": float(item.findtext("wgs84Lon")),
                        "address": item.findtext("dutyAddr"),
                        "phone": item.findtext("dutyTel3")
                    }

        # 2. 실시간 병상 수 전체 가져오기
        beds_data = {}
        for page in range(1, 6):
            url = (
                "https://apis.data.go.kr/B552657/ErmctInfoInqireService/getEmrrmRltmUsefulSckbdInfoInqire"
                f"?serviceKey={SERVICE_KEY}"
                f"&pageNo={page}"
                "&numOfRows=100"
            )
            res = requests.get(url)
            res.encoding = "utf-8"
            root = ET.fromstring(res.text)
            for item in root.findall(".//item"):
                hpid = item.findtext("hpid")
                hvec = item.findtext("hvec")
                if hpid:
                    try:
                        beds_data[hpid.strip()] = int(hvec)
                    except:
                        continue

        # 3. hpid 기준으로 결합 (beds가 없으면 null로 유지)[cite: 9]
        hospitals = []
        for hpid, info in location_data.items():
            hospitals.append({
                "hpid": hpid,
                "name": info["name"],
                "lat": info["lat"],
                "lon": info["lon"],
                "address": info["address"],
                "phone": info["phone"],
                "beds": beds_data.get(hpid) # None(null) 또는 숫자 전송[cite: 9]
            })

        return app.response_class(
            response=json.dumps(hospitals, ensure_ascii=False),
            status=200,
            mimetype="application/json"
        )
    except Exception as e:
        return app.response_class(
            response=json.dumps({"error": str(e)}, ensure_ascii=False),
            status=500,
            mimetype="application/json"
        )

@app.route("/analyze", methods=["POST"])
def analyze():

    data = request.get_json()

    symptom = data.get("symptom", "")
    target=data.get("target","")

    """
    나중에 사용할 AI 서버 호출 코드

    ai_res = requests.post(
        "http://127.0.0.1:8000/ktas",
        json={
            "symptom": symptom,
            "target": target
        }
    )

    ai_data = ai_res.json()

    if ai_data["status"] == "recall":

        return jsonify({
            "status": "recall",
            "message": ai_data["message"]
        })

    ktas = ai_data["ktas"]
    """

    # recall 테스트용
    if symptom == "recall":

        return jsonify({
            "status": "recall",
            "message": "증상을 더 자세히 입력해주세요."
        })

    # 테스트용 KTAS 레벨
    ktas = 2

    # KTAS별 텍스트
    ktas_map = {

        1: {
            "level_text": "소생",
            "message": "즉각적인 생명 구조가 필요합니다.",
            "action": "즉시 응급실 및 소생 처치 필요"
        },

        2: {
            "level_text": "응급",
            "message": "빠른 응급 처치가 필요합니다.",
            "action": "가까운 응급실 방문 권장"
        },

        3: {
            "level_text": "긴급",
            "message": "빠른 진료가 필요합니다.",
            "action": "응급실 또는 야간진료 병원 방문"
        },

        4: {
            "level_text": "준긴급",
            "message": "증상 관찰이 필요합니다.",
            "action": "증상 지속 시 병원 방문을 고려하세요"
        },

        5: {
            "level_text": "비응급",
            "message": "응급 가능성은 낮습니다.",
            "action": "일반 외래 진료를 권장합니다"
        }
    }

    result = {
        "ktas": ktas,
        **ktas_map[ktas]
    }

    return jsonify(result)
    
if __name__ == "__main__":
    app.run(debug=True)