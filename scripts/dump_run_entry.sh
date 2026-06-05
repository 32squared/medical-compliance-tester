#!/bin/bash
# Cloud Run Job 진입점 — GCS 에서 dump_run_to_gcs.py 받아 실행. curl 미설치 환경 대응.
set -e
export DATABASE_URL="postgresql://app_user:${DB_PASSWORD}@/medical_app?host=/cloudsql/medical-compliance-tester:asia-northeast3:medical-db"
pip install -q psycopg2-binary
python3 -c "import urllib.request,ssl; ctx=ssl.create_default_context(); ctx.check_hostname=False; ctx.verify_mode=ssl.CERT_NONE; open('/tmp/dump.py','wb').write(urllib.request.urlopen('https://storage.googleapis.com/medical-compliance-tester-medical-data/scripts/dump_run_to_gcs.py', context=ctx).read())"
python3 /tmp/dump.py
