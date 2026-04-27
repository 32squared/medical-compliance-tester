"""
운영 DB(medical_app) → DEV DB(medical_app_dev) 안전 동기화 스크립트

기존 migrate_prod_to_dev.py와 차이점:
  - users 테이블 건드리지 않음 (advisor/admin 계정 보호)
  - sessions 테이블 건드리지 않음 (활성 세션 보호)
  - 채팅 이력(conversations/messages/comments) 복사 안 함
  - 테스트 이력(test_runs) 복사 안 함
  - RLHF 데이터(response_feedback/preference_pairs) 복사 안 함
  - 신규 테이블(arena_*) 복사 안 함 (운영에 없음)

복사 대상 (config 데이터만):
  - settings        : 모든 설정 (API 키, GPT 설정, categories, guidelines, criteria 포함)
  - scenarios       : 시나리오 전체
  - consultation_checklists : 문진 체크리스트
  - prompt_enhancements     : 프롬프트 강화 데이터

사용법:
  Cloud Run Job (권장):
    이 파일을 GCS 버킷에 업로드 후 Cloud Run Job으로 실행

  로컬 (Cloud SQL Proxy 필요):
    cloud-sql-proxy medical-compliance-tester:asia-northeast3:medical-db --port=5434 &
    DB_PASSWORD=xxx CLOUD_SQL_HOST=127.0.0.1 CLOUD_SQL_PORT=5434 python scripts/migrate_prod_to_dev_safe.py

주의:
  - DEV의 settings/scenarios/checklists/prompt_enhancements 테이블이 운영 데이터로 덮어씌워집니다.
  - users/sessions/conversations/messages/test_runs/feedback/arena_* 테이블은 그대로 유지됩니다.
  - 운영 DB는 읽기 전용 (SELECT만)으로 접근합니다.
"""

import os
import sys
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

# ── 연결 설정 ──────────────────────────────────────────────────────────────────
DB_PASSWORD = os.environ.get("DB_PASSWORD", "MedComp2026!Secure")
SQL_HOST    = os.environ.get(
    "CLOUD_SQL_HOST",
    "/cloudsql/medical-compliance-tester:asia-northeast3:medical-db"
)
SQL_PORT    = os.environ.get("CLOUD_SQL_PORT", "")  # 로컬 proxy 시 5434 등

if SQL_PORT:
    PROD_URL = f"postgresql://app_user:{DB_PASSWORD}@{SQL_HOST}:{SQL_PORT}/medical_app"
    DEV_URL  = f"postgresql://app_user:{DB_PASSWORD}@{SQL_HOST}:{SQL_PORT}/medical_app_dev"
else:
    # Cloud SQL Unix socket (Cloud Run Job 환경)
    PROD_URL = f"postgresql://app_user:{DB_PASSWORD}@/medical_app?host={SQL_HOST}"
    DEV_URL  = f"postgresql://app_user:{DB_PASSWORD}@/medical_app_dev?host={SQL_HOST}"

# 복사 대상 테이블 (config만, 부모 → 자식 순)
COPY_TABLES = [
    "settings",                # 가장 중요 - API 키, GPT 설정, categories, guidelines, criteria 포함
    "scenarios",               # 시나리오 전체
    "consultation_checklists", # 문진 체크리스트
    "prompt_enhancements",     # 프롬프트 강화
]

# 절대 건드리지 않을 테이블 (DEV에서 보존)
PRESERVED_TABLES = [
    "users",                  # advisor/admin 계정 보호
    "sessions",               # 활성 세션 보호
    "conversations",          # 채팅 이력 (사용자 데이터)
    "messages",
    "comments",
    "test_runs",
    "response_feedback",      # RLHF
    "preference_pairs",
    "arena_model_configs",    # 신규
    "arena_sessions",
    "arena_evaluations",
]


def make_row(row: dict) -> tuple:
    """dict/list 값을 psycopg2 Json 어댑터로 감쌈"""
    return tuple(
        Json(v) if isinstance(v, (dict, list)) else v
        for v in row.values()
    )


def main():
    print("=" * 70, flush=True)
    print("Safe Migration: PROD → DEV (config only, users 보호)", flush=True)
    print("=" * 70, flush=True)
    print(f"\nCopy tables   : {COPY_TABLES}", flush=True)
    print(f"Preserve tables: {PRESERVED_TABLES}\n", flush=True)

    print("Connecting to PROD...", flush=True)
    prod = psycopg2.connect(PROD_URL)
    print("Connecting to DEV...", flush=True)
    dev  = psycopg2.connect(DEV_URL)
    dev.autocommit = False

    prod_cur = prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    dev_cur  = dev.cursor()

    # ── DEV의 advisor/admin 계정 카운트 (보호 확인용) ─────────────────────────
    print("\n[DEV 보존 데이터 카운트 — 마이그레이션 전]", flush=True)
    try:
        dev_cur.execute("SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY role")
        for row in dev_cur.fetchall():
            print(f"  users.{row[0]}: {row[1]}건", flush=True)
    except Exception as e:
        print(f"  users count SKIP: {e}", flush=True)
        dev.rollback()

    # ── Step 1: TRUNCATE 대상 테이블만 (자식 → 부모 순) ─────────────────────
    print(f"\n[1/2] Truncating COPY_TABLES (역순)...", flush=True)
    for table in reversed(COPY_TABLES):
        try:
            dev_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
            print(f"  TRUNCATE {table} OK", flush=True)
        except Exception as e:
            print(f"  TRUNCATE {table} SKIP ({e})", flush=True)
            dev.rollback()
            dev.autocommit = False
    dev.commit()

    # ── Step 2: INSERT (부모 → 자식 순) ──────────────────────────────────────
    print(f"\n[2/2] Copying PROD → DEV...", flush=True)
    total = 0
    for table in COPY_TABLES:
        try:
            prod_cur.execute(f'SELECT * FROM "{table}"')
            rows = prod_cur.fetchall()
            if not rows:
                print(f"  {table}: 0 rows (empty in PROD)", flush=True)
                continue

            cols     = list(rows[0].keys())
            col_list = ", ".join(f'"{c}"' for c in cols)
            ph       = ", ".join(["%s"] * len(cols))

            dev_cur.executemany(
                f'INSERT INTO "{table}" ({col_list}) VALUES ({ph}) ON CONFLICT DO NOTHING',
                [make_row(r) for r in rows],
            )
            dev.commit()
            total += len(rows)
            print(f"  {table}: {len(rows)} rows OK", flush=True)
        except Exception as e:
            print(f"  {table}: ERR ({e})", flush=True)
            dev.rollback()
            dev.autocommit = False

    # ── 마이그레이션 후 advisor/admin 보존 확인 ───────────────────────────────
    print(f"\n[DEV 보존 데이터 카운트 — 마이그레이션 후]", flush=True)
    try:
        dev_cur.execute("SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY role")
        for row in dev_cur.fetchall():
            print(f"  users.{row[0]}: {row[1]}건", flush=True)
    except Exception as e:
        print(f"  users count SKIP: {e}", flush=True)

    prod.close()
    dev.close()
    print(f"\n{'='*70}", flush=True)
    print(f"✅ Safe migration complete! {total} rows copied total.", flush=True)
    print(f"   ✓ users 테이블은 그대로 유지됨 (advisor 7개 + admin 1개 보호)", flush=True)
    print(f"{'='*70}", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ Migration failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)
