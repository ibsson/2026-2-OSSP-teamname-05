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
    target = data.get("target", "")

    target_label = "소아" if target == "pediatric" else "성인"
    symptom_with_target = f"({target_label}) {symptom}"

    ai_res = requests.post(
        "http://127.0.0.1:8000/predict",
        json={"symptom_text": symptom_with_target}
    )
    ai_data = ai_res.json()

    ktas_map = {
        1: {"level_text":"소생","message":"즉각적인 생명 구조가 필요합니다.","action":"즉시 응급실 및 소생 처치 필요"},
        2: {"level_text":"응급","message":"빠른 응급 처치가 필요합니다.","action":"가까운 응급실 방문 권장"},
        3: {"level_text":"긴급","message":"빠른 진료가 필요합니다.","action":"응급실 또는 야간진료 병원 방문"},
        4: {"level_text":"준긴급","message":"증상 관찰이 필요합니다.","action":"증상 지속 시 병원 방문을 고려하세요"},
        5: {"level_text":"비응급","message":"응급 가능성은 낮습니다.","action":"일반 외래 진료를 권장합니다"},
    }
    ktas = ai_data["ktas_level"]

    return jsonify({
        "ktas": ktas,
        **ktas_map[ktas],
        "adjusted":           ai_data.get("adjusted", False),
        "original_level":     ai_data.get("original_level"),
        "adjusted_reason":    ai_data.get("adjusted_reason"),
        "highlight_keywords": ai_data.get("highlight_keywords", []),
        "dept":               ai_data.get("dept"),
        "dept_confidence":    ai_data.get("dept_confidence"),
    })
    
if __name__ == "__main__":
    app.run(debug=True)