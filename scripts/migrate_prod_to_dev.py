"""
운영 DB(medical_app) → DEV DB(medical_app_dev) 데이터 동기화 스크립트

사용법:
  로컬 (Cloud SQL Proxy 필요):
    cloud-sql-proxy medical-compliance-tester:asia-northeast3:medical-db --port=5434 &
    DB_PASSWORD=xxx python scripts/migrate_prod_to_dev.py

  Cloud Run Job (권장):
    gcloud run jobs create db-migrate-prod-to-dev \
      --image gcr.io/medical-compliance-tester/medical-compliance-tester-dev \
      --region asia-northeast3 \
      --project medical-compliance-tester \
      --set-cloudsql-instances medical-compliance-tester:asia-northeast3:medical-db \
      --vpc-connector=medical-connector \
      --vpc-egress=all-traffic \
      --set-env-vars DB_PASSWORD=xxx \
      --command bash \
      --args="-c,pip install google-cloud-storage -q && gsutil cp gs://medical-compliance-tester-medical-data/scripts/migrate_prod_to_dev.py /tmp/migrate.py && python3 /tmp/migrate.py" \
      --max-retries=0
    gcloud run jobs execute db-migrate-prod-to-dev --region asia-northeast3 --wait

주의:
  - DEV DB의 모든 데이터가 운영 데이터로 덮어씌워집니다.
  - 운영 DB는 읽기 전용으로만 접근합니다 (데이터 변경 없음).
"""

import os
import psycopg2
import psycopg2.extras
from psycopg2.extras import Json

# ── 연결 설정 ──────────────────────────────────────────────────────────────────
DB_PASSWORD = os.environ.get("DB_PASSWORD", "MedComp2026!Secure")
SQL_HOST    = os.environ.get(
    "CLOUD_SQL_HOST",
    "/cloudsql/medical-compliance-tester:asia-northeast3:medical-db"
)

PROD_URL = f"postgresql://app_user:{DB_PASSWORD}@/medical_app?host={SQL_HOST}"
DEV_URL  = f"postgresql://app_user:{DB_PASSWORD}@/medical_app_dev?host={SQL_HOST}"

# FK 의존성 순서: 자식 → 부모 (TRUNCATE 순서)
TRUNCATE_ORDER = [
    "comments",
    "test_runs",
    "messages",
    "consultation_checklists",
    "prompt_enhancements",
    "conversations",
    "sessions",
    "settings",
    "scenarios",
    "users",
]
# INSERT 순서: 부모 → 자식
INSERT_ORDER = list(reversed(TRUNCATE_ORDER))


def make_row(row: dict) -> tuple:
    """dict/list 값을 psycopg2 Json 어댑터로 감쌈"""
    return tuple(
        Json(v) if isinstance(v, (dict, list)) else v
        for v in row.values()
    )


def main():
    print("Connecting to PROD...", flush=True)
    prod = psycopg2.connect(PROD_URL)
    print("Connecting to DEV...", flush=True)
    dev  = psycopg2.connect(DEV_URL)
    dev.autocommit = False

    prod_cur = prod.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    dev_cur  = dev.cursor()

    # ── Step 1: TRUNCATE (자식 → 부모) ──────────────────────────────────────
    print("\n[1/2] Truncating DEV tables...", flush=True)
    for table in TRUNCATE_ORDER:
        try:
            dev_cur.execute(f'TRUNCATE TABLE "{table}" CASCADE')
            print(f"  TRUNCATE {table} OK", flush=True)
        except Exception as e:
            print(f"  TRUNCATE {table} SKIP ({e})", flush=True)
            dev.rollback()
            dev.autocommit = False
    dev.commit()

    # ── Step 2: INSERT (부모 → 자식) ────────────────────────────────────────
    print("\n[2/2] Copying data PROD → DEV...", flush=True)
    total = 0
    for table in INSERT_ORDER:
        try:
            prod_cur.execute(f'SELECT * FROM "{table}"')
            rows = prod_cur.fetchall()
            if not rows:
                print(f"  {table}: 0 rows (empty)", flush=True)
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

    prod.close()
    dev.close()
    print(f"\n✅ Migration complete! {total} rows copied total.", flush=True)


if __name__ == "__main__":
    main()
