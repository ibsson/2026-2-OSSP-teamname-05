from urllib.parse import quote_plus
import time

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool

from config import (
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_DB,
    POSTGRES_USER,
    POSTGRES_PASSWORD,
)


MAX_DB_RETRIES = 3
RETRY_SLEEP_SECONDS = 3


def get_postgres_engine():
    """
    Supabase pooler의 session connection 초과를 막기 위해 SQLAlchemy 자체 풀을 쓰지 않는다.
    DB 작업 1회마다 연결을 열고, 작업 후 dispose()로 즉시 정리한다.
    """
    if not all([
        POSTGRES_HOST,
        POSTGRES_PORT,
        POSTGRES_DB,
        POSTGRES_USER,
        POSTGRES_PASSWORD,
    ]):
        print("PostgreSQL 접속 정보가 .env에 없습니다. DB 저장/읽기를 건너뜁니다.")
        return None

    encoded_password = quote_plus(POSTGRES_PASSWORD)

    url = (
        f"postgresql+psycopg2://{POSTGRES_USER}:{encoded_password}"
        f"@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
    )

    return create_engine(
        url,
        poolclass=NullPool,      # 연결을 풀에 보관하지 않음
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "application_name": "prediction_worker",
        },
    )


def _is_max_connection_error(error: Exception) -> bool:
    msg = str(error).lower()
    return (
        "emaxconnsession" in msg
        or "max clients reached" in msg
        or "too many clients" in msg
        or "remaining connection slots" in msg
    )


def _sleep_before_retry(attempt: int):
    wait_seconds = RETRY_SLEEP_SECONDS * attempt
    print(f"DB 연결 초과 가능성. {wait_seconds}초 후 재시도합니다. ({attempt}/{MAX_DB_RETRIES})")
    time.sleep(wait_seconds)


def replace_table(df: pd.DataFrame, table_name: str):
    """
    테이블 구조는 유지하고 데이터만 교체한다.
    pandas to_sql(if_exists='replace')는 테이블을 DROP할 수 있으므로 사용하지 않는다.
    """
    if df is None or df.empty:
        print(f"{table_name}: 저장할 데이터가 없습니다.")
        return False

    last_error = None

    for attempt in range(1, MAX_DB_RETRIES + 1):
        engine = get_postgres_engine()

        if engine is None:
            return False

        try:
            with engine.begin() as conn:
                conn.execute(text(f"DELETE FROM {table_name}"))
                df.to_sql(
                    table_name,
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=500,
                )

            print(f"PostgreSQL 저장 완료: {table_name}, 행 수: {len(df)}")
            return True

        except OperationalError as e:
            last_error = e
            print(f"PostgreSQL 저장 실패: {table_name}")
            print(e)

            if _is_max_connection_error(e) and attempt < MAX_DB_RETRIES:
                _sleep_before_retry(attempt)
                continue
            return False

        except Exception as e:
            last_error = e
            print(f"PostgreSQL 저장 실패: {table_name}")
            print(e)
            return False

        finally:
            engine.dispose()

    if last_error is not None:
        print(f"PostgreSQL 저장 최종 실패: {table_name}")
        print(last_error)

    return False


def append_table(df: pd.DataFrame, table_name: str):
    """
    검증 결과처럼 누적 저장할 때 사용한다.
    """
    if df is None or df.empty:
        print(f"{table_name}: 저장할 데이터가 없습니다.")
        return False

    last_error = None

    for attempt in range(1, MAX_DB_RETRIES + 1):
        engine = get_postgres_engine()

        if engine is None:
            return False

        try:
            with engine.begin() as conn:
                df.to_sql(
                    table_name,
                    conn,
                    if_exists="append",
                    index=False,
                    method="multi",
                    chunksize=500,
                )

            print(f"PostgreSQL 누적 저장 완료: {table_name}, 행 수: {len(df)}")
            return True

        except OperationalError as e:
            last_error = e
            print(f"PostgreSQL 누적 저장 실패: {table_name}")
            print(e)

            if _is_max_connection_error(e) and attempt < MAX_DB_RETRIES:
                _sleep_before_retry(attempt)
                continue
            return False

        except Exception as e:
            last_error = e
            print(f"PostgreSQL 누적 저장 실패: {table_name}")
            print(e)
            return False

        finally:
            engine.dispose()

    if last_error is not None:
        print(f"PostgreSQL 누적 저장 최종 실패: {table_name}")
        print(last_error)

    return False


def read_table_from_postgres(table_name: str) -> pd.DataFrame:
    """검증 단계에서 사용하기 위한 안전한 테이블 읽기 함수."""
    last_error = None

    for attempt in range(1, MAX_DB_RETRIES + 1):
        engine = get_postgres_engine()

        if engine is None:
            return pd.DataFrame()

        try:
            with engine.connect() as conn:
                return pd.read_sql(text(f"SELECT * FROM {table_name}"), conn)

        except OperationalError as e:
            last_error = e
            print(f"{table_name} 읽기 실패:", e)

            if _is_max_connection_error(e) and attempt < MAX_DB_RETRIES:
                _sleep_before_retry(attempt)
                continue
            return pd.DataFrame()

        except Exception as e:
            last_error = e
            print(f"{table_name} 읽기 실패:", e)
            return pd.DataFrame()

        finally:
            engine.dispose()

    if last_error is not None:
        print(f"{table_name} 읽기 최종 실패:", last_error)

    return pd.DataFrame()


def delete_rows_by_ids(table_name: str, id_column: str, ids):
    """prediction_id 목록 같은 키 기반 삭제를 안전하게 수행한다."""
    if not ids:
        return False

    last_error = None

    for attempt in range(1, MAX_DB_RETRIES + 1):
        engine = get_postgres_engine()

        if engine is None:
            return False

        try:
            with engine.begin() as conn:
                conn.execute(
                    text(f"DELETE FROM {table_name} WHERE {id_column} = ANY(:ids)"),
                    {"ids": list(ids)},
                )

            print(f"{table_name} 삭제 완료: {len(ids)}행")
            return True

        except OperationalError as e:
            last_error = e
            print(f"{table_name} 삭제 실패:", e)

            if _is_max_connection_error(e) and attempt < MAX_DB_RETRIES:
                _sleep_before_retry(attempt)
                continue
            return False

        except Exception as e:
            last_error = e
            print(f"{table_name} 삭제 실패:", e)
            return False

        finally:
            engine.dispose()

    if last_error is not None:
        print(f"{table_name} 삭제 최종 실패:", last_error)

    return False
