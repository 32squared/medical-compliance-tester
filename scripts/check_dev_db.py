"""DEV DB 진단 — 실제 데이터 존재 확인"""
import os
import psycopg2

DB_PASSWORD = os.environ.get("DB_PASSWORD", "MedComp2026!Secure")
SQL_HOST    = os.environ.get(
    "CLOUD_SQL_HOST",
    "/cloudsql/medical-compliance-tester:asia-northeast3:medical-db"
)

DEV_URL  = f"postgresql://app_user:{DB_PASSWORD}@/medical_app_dev?host={SQL_HOST}"
PROD_URL = f"postgresql://app_user:{DB_PASSWORD}@/medical_app?host={SQL_HOST}"

print("=" * 70, flush=True)
print("DB 진단 — DEV vs PROD 데이터 비교", flush=True)
print("=" * 70, flush=True)

for label, url in [("PROD", PROD_URL), ("DEV", DEV_URL)]:
    print(f"\n--- {label} DB ({url.split('@')[1].split('?')[0].lstrip('/')}) ---", flush=True)
    try:
        conn = psycopg2.connect(url)
        cur = conn.cursor()
        for table in ["users", "settings", "scenarios", "consultation_checklists", "prompt_enhancements"]:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{table}"')
                count = cur.fetchone()[0]
                print(f"  {table:30s}: {count:5d} rows", flush=True)
            except Exception as e:
                print(f"  {table:30s}: ERR {str(e)[:60]}", flush=True)
                conn.rollback()
        # users 상세
        try:
            cur.execute('SELECT role, COUNT(*) FROM users GROUP BY role ORDER BY role')
            for row in cur.fetchall():
                print(f"    users.{row[0]:10s}: {row[1]} 건", flush=True)
        except Exception as e:
            print(f"    users role: ERR {e}", flush=True)
        # settings 키 일부
        try:
            cur.execute('SELECT key FROM settings ORDER BY key LIMIT 20')
            keys = [r[0] for r in cur.fetchall()]
            print(f"    settings keys: {keys}", flush=True)
        except Exception as e:
            print(f"    settings keys: ERR {e}", flush=True)
        # scenarios 샘플
        try:
            cur.execute('SELECT id, title FROM scenarios LIMIT 3')
            for row in cur.fetchall():
                print(f"    scenario sample: {row[0]} - {row[1][:50] if row[1] else ''}", flush=True)
        except Exception as e:
            print(f"    scenarios sample: ERR {e}", flush=True)
        conn.close()
    except Exception as e:
        print(f"  CONNECT ERR: {e}", flush=True)

print("\n" + "=" * 70, flush=True)
print("진단 완료", flush=True)
print("=" * 70, flush=True)
