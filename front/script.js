let map;
let currentMarker;
let hospitalMarkers = [];

window.onload = function () {
  initMap();
  getCurrentLocation();
  loadHospitals();
  initNavigation();
  initSymptomLogic();

  document.getElementById("currentLocationBtn").onclick = () => getCurrentLocation();
  document
    .getElementById("startServiceBtn")
    .onclick = () => {

      document
        .getElementById("introOverlay")
        .remove();

      getCurrentLocation();
    };
};

function initMap() {

  map = L.map("map", {
    zoomControl: false
  }).setView([37.5665, 126.9780], 15);

  L.tileLayer(
    "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png",
    {
      attribution: "&copy; OpenStreetMap contributors"
    }
  ).addTo(map);
}

function initNavigation() {
  const goSymptomBtn = document.getElementById("goSymptom");
  const goMapBtn = document.getElementById("goMap");
  const symptomSec = document.getElementById("symptomSection");

  goSymptomBtn.onclick = () => {
    symptomSec.classList.remove("hidden");
    goSymptomBtn.classList.add("active");
    goMapBtn.classList.remove("active");
  };

  goMapBtn.onclick = () => {
    symptomSec.classList.add("hidden");
    goMapBtn.classList.add("active");
    goSymptomBtn.classList.remove("active");
    if (map) {
      setTimeout(() => {
        map.invalidateSize();
      }, 100);
    }
  };
}

function initSymptomLogic() {
  const input = document.getElementById("symptomInput");
  const analyzeBtn = document.getElementById("analyzeBtn");

  // 입력 여부에 따른 버튼 활성화
  const checkInput = () => {
    if (input.value.trim().length > 0) {
      analyzeBtn.disabled = false;
      analyzeBtn.classList.add("ready");
    } else {
      analyzeBtn.disabled = true;
      analyzeBtn.classList.remove("ready");
    }
  };

  input.oninput = checkInput;

  // 예시 증상 클릭 시 입력창에 넣기
  document.querySelectorAll(".ex-item").forEach(item => {
    item.onclick = () => {
      input.value = item.innerText;
      checkInput();
    };
  });

  // 대상 선택
  document.querySelectorAll(".target-card").forEach(card => {
    card.onclick = () => {
      document.querySelectorAll(".target-card").forEach(c => c.classList.remove("active"));
      card.classList.add("active");
    };
  });
}

// 지도 데이터 로드 로직 (기존 유지)
async function loadHospitals() {
  try {
    const res = await fetch("http://127.0.0.1:5000/hospitals");
    const data = await res.json();
    window.hospitalData = data;
    data.forEach(h => {
      let color;
      let bedDisplay = h.beds;
      if (h.beds === null || h.beds === undefined || h.beds === "N/A") {
        color = "#9ca3af"; bedDisplay = "N/A";
      } else {
        const bedsNum = parseInt(h.beds);
        bedDisplay = h.beds;
        if (bedsNum <= 0) color = "#ef4444";
        else if (bedsNum > 5) color = "#16a34a";
        else color = "#f59e0b";
      }
      const markerHTML = `<div style="position:relative; width:36px; height:36px; background:white; border:3px solid ${color}; border-radius:50%; display:flex; align-items:center; justify-content:center; font-weight:700; color:${color}; box-shadow:0 4px 10px rgba(0,0,0,0.15);">+<div style="position:absolute; top:-10px; right:-10px; background:${color}; color:white; font-size:10px; padding:2px 6px; border-radius:10px; border:1px solid white; min-width:20px; text-align:center;">${bedDisplay}</div></div>`;
      const icon = L.divIcon({
        html: markerHTML,
        className: "",
        iconSize: [36, 36]
      });

      const marker = L.marker(
        [h.lat, h.lon],
        {
          icon: icon
        }
      )
        .addTo(map)
        .bindTooltip(h.name, {
          direction: "top",
          offset: [0, -20]
        });

      hospitalMarkers.push(marker);
    });
  } catch (e) { console.error(e); }
}

function getCurrentLocation() {
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition((pos) => {
      const lat = pos.coords.latitude;
      const lon = pos.coords.longitude;

      map.setView([lat, lon], 15);

      if (currentMarker) {
        map.removeLayer(currentMarker);
      }

      const currentIcon = L.divIcon({
        html: `
    <div style="
      width:18px;
      height:18px;
      background:#3b82f6;
      border:3px solid white;
      border-radius:50%;
      box-shadow:0 0 12px rgba(59,130,246,0.6);
    "></div>
  `,
        className: "",
        iconSize: [18, 18]
      });

      currentMarker = L.marker(
        [lat, lon],
        { icon: currentIcon }
      ).addTo(map);
    });
  }
}

document.getElementById("analyzeBtn").onclick = async () => {

  const symptom =
    document.getElementById("symptomInput").value;
  const target =
    document.querySelector(".target-card.active")
      .dataset.target;
  try {

    const res = await fetch(
      "http://127.0.0.1:5000/analyze",
      {
        method: "POST",

        headers: {
          "Content-Type": "application/json"
        },

        body: JSON.stringify({
          symptom: symptom,
          target: target
        })
      }
    );

    const data = await res.json();

    if (data.status === "recall") {

      showRecallMessage(data.message);

    } else {

      const label =
        document.querySelector(".symptom-label");

      label.innerText =
        "현재 증상을 자세히 설명해주세요";

      label.style.color = "#1e293b";

      showResult(data);
    }
  } catch (e) {
    console.error(e);
  }
};

function showResult(data) {

  const colors = {
    1: "#ef4444",
    2: "#f97316",
    3: "#facc15",
    4: "#10b981",
    5: "#60a5fa"
  };

  const color = colors[data.ktas];

  const resultHTML = `

  <div class="ktas-result-overlay">

    <div class="ktas-result-card">

      <div
        class="ktas-icon-wrap"
        style="
          background:${color}22;
          box-shadow:0 0 40px ${color}33;
        "
      >
        <div
          class="ktas-icon"
          style="color:${color}"
        >
          ⚠
        </div>
      </div>

      <h1
        class="ktas-title"
        style="color:${color}"
      >
        KTAS ${data.ktas}단계 - ${data.level_text}
      </h1>

      <p class="ktas-desc">
        ${data.message}
      </p>

      <div
        class="ktas-action-box"
        style="background:${color}22"
      >

        <div
          class="ktas-action-title"
          style="color:${color}"
        >
          권장 조치
        </div>

        <div
          class="ktas-action-desc"
          style="color:${color}"
        >
          ${data.action}
        </div>

      </div>

      <div class="ktas-level-wrap">

        <div class="ktas-level-item">
          <div class="ktas-bar red"></div>
          <span>1단계</span>
        </div>

        <div class="ktas-level-item">
          <div class="ktas-bar orange"></div>
          <span>2단계</span>
        </div>

        <div class="ktas-level-item">
          <div class="ktas-bar yellow"></div>
          <span>3단계</span>
        </div>

        <div class="ktas-level-item">
          <div class="ktas-bar green"></div>
          <span>4단계</span>
        </div>

        <div class="ktas-level-item">
          <div class="ktas-bar blue"></div>
          <span>5단계</span>
        </div>

      </div>

      <button
        class="hospital-btn"
        onclick="showHospitalList()"
        style="
          background:${color};
          box-shadow:0 12px 30px ${color}55;
        "
      >
        병원 추천 보기 →
      </button>

      <p class="ktas-footer">
        * 이 분석은 참고용이며 정확한 진단은
        의료 전문가와 상담하세요
      </p>

    </div>

  </div>
  `;

  document.body.insertAdjacentHTML(
    "beforeend",
    resultHTML
  );
}

function showHospitalList(sortType="ai") {
  document
    .querySelector(".hospital-list-overlay")
    ?.remove();

  let hospitals = [...window.hospitalData];

  if (sortType === "ai") {

    hospitals.sort((a, b) => {

      const aBeds = a.beds ?? -1;
      const bBeds = b.beds ?? -1;

      return bBeds - aBeds;
    });

  } else if (sortType === "distance") {

    if (currentMarker) {

      const current =
        currentMarker.getLatLng();

      hospitals.sort((a, b) => {

        const distA =
          map.distance(
            [current.lat, current.lng],
            [a.lat, a.lon]
          );

        const distB =
          map.distance(
            [current.lat, current.lng],
            [b.lat, b.lon]
          );

        return distA - distB;
      });
    }
  }

  hospitals = hospitals.slice(0, 3);

  const html = `

  <div class="hospital-list-overlay">

    <div class="hospital-list-page">

    <h1 class="hospital-list-title">
    추천 병원 목록
  </h1>
  
  <div class="hospital-sort-wrap">
  
    <button
      class="
        hospital-sort-btn
        ${sortType === "ai" ? "active" : ""}
      "
      onclick="showHospitalList('ai')"
    >
    ✨ AI추천순
    </button>
  
    <button
      class="
        hospital-sort-btn
        ${sortType === "distance" ? "active" : ""}
      "
      onclick="showHospitalList('distance')"
    >
    ⇅ 거리순
    </button>
  
  </div>
  
  <p class="hospital-list-sub">
    도착 예상 시간 기준으로 병상 가용 가능성이 높은 순서입니다
  </p>

      ${hospitals.map((h, index) => hospitalCard(

    h.name,
    h.address ?? "주소 정보 없음",
    h.phone ?? "전화번호 없음",
    "계산중",
    "계산중",
    h.beds ?? "N/A",
    "예측중",
    `${index + 1}순위`,
    h.lat,
    h.lon

  )).join("")}

      <div class="hospital-info-footer">

        <h3>가용 가능성 계산 방식</h3>

        <p>
          과거 시간대별 병상 사용 패턴을 분석하여,
          귀하가 도착할 예상 시간에 해당 병원의 병상이
          남아있을 확률을 AI가 예측한 결과입니다.
        </p>

      </div>

    </div>

  </div>
  `;

  document.body.insertAdjacentHTML(
    "beforeend",
    html
  );
}

function hospitalCard(
  name,
  address,
  phone,
  distance,
  eta,
  beds,
  probability,
  rank,
  lat,
  lon
) {

  return `

  <div class="hospital-card">

    <div class="hospital-card-top">

      <div>

        <div class="hospital-tags">

          <span class="hospital-rank-tag">
            ${rank}
          </span>

          <span class="hospital-region-tag">
            지역응급의료센터
          </span>

        </div>

        <h2 class="hospital-name">
          ${name}
        </h2>

        <div class="hospital-meta">
          📍 ${address}
        </div>

        <div class="hospital-meta">
          📞 ${phone}
        </div>

      </div>

      <div class="hospital-score">

        ${probability}

        <span>
          가용 가능성
        </span>

      </div>

    </div>

    <div class="hospital-divider"></div>

    <div class="hospital-bottom-info">

      <div class="hospital-info-box">
        <span>거리</span>
        <strong>${distance}</strong>
      </div>

      <div class="hospital-info-box">
        <span>예상 도착 시간</span>
        <strong>${eta}</strong>
      </div>

      <div class="hospital-info-box">
        <span>현재 병상</span>
        <strong>${beds}</strong>
      </div>

    </div>

    <button
  class="route-view-btn"
  onclick='showRoute({
    name: "${name}",
    lat: ${lat},
    lon: ${lon},
    eta: "${eta}",
    distance: "${distance}",
    beds: "${beds}",
    probability: "${probability}"
  })'
>
  📍 지도에서 경로 보기
</button>

  </div>
  `;
}

function showRecallMessage(message) {

  const label =
    document.querySelector(".label-text");

  label.innerText = message;

  label.style.color = "#dc2626";

  document
    .getElementById("symptomInput")
    .focus();
}

let currentRoute;

async function showRoute(hospital) {

  document
    .querySelector(".hospital-list-overlay")
    ?.remove();

  document
    .querySelector(".ktas-result-overlay")
    ?.remove();

  document
    .getElementById("symptomSection")
    .classList.add("hidden");

  setTimeout(() => {
    map.invalidateSize();
  }, 200);

  document
    .getElementById("goMap")
    .classList.add("active");

  document
    .getElementById("goSymptom")
    .classList.remove("active");

  hospitalMarkers.forEach(marker => {
    map.removeLayer(marker);
  });

  const selectedHospitalMarker = L.marker(
    [hospital.lat, hospital.lon]
  ).addTo(map);

  selectedHospitalMarker.bindTooltip(
    hospital.name,
    {
      direction: "top"
    }
  );

  if (!currentMarker) return;

  const start =
    currentMarker.getLatLng();

  try {

    const res = await fetch(
      "http://127.0.0.1:8000/get-route",
      {

        method: "POST",

        headers: {
          "Content-Type":
            "application/json"
        },

        body: JSON.stringify({

          start_lat: start.lat,
          start_lon: start.lng,

          end_lat: hospital.lat,
          end_lon: hospital.lon
        })
      }
    );

    const data = await res.json();

    console.log(data);

    if (currentRoute) {
      map.removeLayer(currentRoute);
    }

    const pathCoords =
      data.path.map(point => [
        point[1],
        point[0]
      ]);

    currentRoute = L.polyline(
      pathCoords,
      {
        color: "#ef4444",
        weight: 4,
        opacity: 0.9,
        lineCap: "round",
        lineJoin: "round"
      }
    ).addTo(map);

    map.fitBounds(
      currentRoute.getBounds(),
      {
        padding: [60, 60]
      }
    );

    showRouteInfo({
      ...hospital,

      eta:
        Math.round(data.total_time_minutes)
        + "분",

      distance:
        (data.total_distance_meters / 1000)
          .toFixed(1)
        + "km"
    });

  } catch (e) {

    console.error(e);

  }
}

function showRouteInfo(hospital) {

  const old =
    document.querySelector(".route-info-card");

  if (old) old.remove();

  const html = `

    <div class="route-info-card">

      <h2>${hospital.name}</h2>

      <div class="route-info-row">
        <span>도착 시간</span>
        <strong>${hospital.eta}</strong>
      </div>

      <div class="route-info-row">
        <span>거리</span>
        <strong>${hospital.distance}</strong>
      </div>

      <div class="route-info-row">
        <span>병상</span>
        <strong>${hospital.beds}</strong>
      </div>

      <div class="route-info-row">
        <span>가용성</span>
        <strong>${hospital.probability}</strong>
      </div>

    </div>
  `;

  document.body.insertAdjacentHTML(
    "beforeend",
    html
  );
}