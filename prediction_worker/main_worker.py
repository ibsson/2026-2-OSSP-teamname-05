import time
from datetime import datetime

from config import COLLECT_INTERVAL_SECONDS
from collect_api import collect_realtime_beds_once, append_realtime_history
from predict_90min import run_prediction_90min
from validator import validate_pending_predictions


def run_one_loop():
    print("\n" + "=" * 100)
    print("현재 시각:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    print("\n1. 실시간 API 1회 수집")
    new_df = collect_realtime_beds_once()

    print("\n2. 최근 3시간 20분 이력 저장")
    history_df = append_realtime_history(new_df)

    if history_df.empty:
        print("이번 루프에서 저장된 이력이 없습니다.")
        return

    print("\n현재까지 이력 상태")
    print("행 수:", len(history_df))
    print("병원 수:", history_df["hpid"].nunique())

    print("\n3. 10~90분 병상 예측")
    result_df, pending_df = run_prediction_90min()

    if result_df.empty:
        print("이번 루프에서는 아직 예측 결과가 생성되지 않았습니다.")
    else:
        print("예측 결과 생성 완료")
        print("예측 병원 수:", len(result_df))
        print("pending 예측 행 수:", len(pending_df))

    print("\n4. 예측 결과 검증")
    validation_df = validate_pending_predictions()

    if validation_df.empty:
        print("이번 루프에서는 검증 결과가 생성되지 않았습니다.")
    else:
        print("검증 결과 생성 완료")
        print("검증 행 수:", len(validation_df))


if __name__ == "__main__":
    while True:
        try:
            run_one_loop()
            print("\n10분 후 다시 실행합니다. 종료하려면 Ctrl+C")
            time.sleep(COLLECT_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nworker를 종료합니다.")
            break

        except Exception as e:
            print("실행 중 오류:", e)
            print("10분 후 다시 시도합니다.")
            time.sleep(COLLECT_INTERVAL_SECONDS)