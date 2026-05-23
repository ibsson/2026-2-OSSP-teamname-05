# 2026-2-OSSP-teamname-05

응급실 병상 예측 및 KTAS 기반 병원 추천 시스템

## Project Structure

- frontend: 웹 프론트엔드
- backend: 백엔드 API 서버
- prediction_worker: 실시간 병상 수집 및 GRU 기반 병상 예측 worker
- ktas_model: 중증도 분류 모델
- data: 기준 데이터
- docs: 문서 및 보고서 자료

## Branch Strategy

- main: 최종 안정 버전
- frontend: 프론트엔드 통합 branch
- backend: 백엔드 통합 branch
- prediction: 병상 예측 worker 통합 branch
- ktas: 중증도 분류 모델 통합 branch

각 팀원은 개인 branch에서 작업한 후 파트 branch로 Pull Request를 보냅니다.

## Do Not Commit

- .env
- *.pem
- API keys
- DB passwords
- venv/
- model files such as .pt, .pkl

- main에는 직접 push 금지.
각자 개인 branch에서 작업.
작업 완료 후 개인 branch → 파트 branch로 Pull Request.
파트 branch 테스트 후 main으로 Pull Request.

프론트는 frontend/이름 branch
백엔드는 backend/이름 branch
중증도 모델은 ktas/이름 branch
병상 예측은 prediction/이름 branch

예를 들어 프론트 팀원이 작업 시작할 때:

git clone https://github.com/ibsson/2026-2-OSSP-teamname-05.git
cd 2026-2-OSSP-teamname-05

git checkout frontend
git pull origin frontend
git checkout -b frontend/팀원이름

작업 끝나면:

git add .
git commit -m "Add frontend main page"
git push origin frontend/팀원이름

그다음 GitHub에서:

frontend/팀원이름 → frontend
