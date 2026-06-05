"""Cloud Run Job 에서 실행 — 특정 run 데이터를 GCS 로 덤프.

환경변수:
  DUMP_RUN_ID      — 덤프할 runId
  DUMP_GCS_PATH    — 결과 업로드 경로 (예: gs://bucket/dumps/run-xxx.json)
  DATABASE_URL     — Cloud SQL 연결 (Cloud Run env 에서 자동 주입)

사용:
  gcloud run jobs execute dump-run --update-env-vars DUMP_RUN_ID=...,DUMP_GCS_PATH=...
"""
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

# 의존성: 이미지에 psycopg2-binary 가 이미 설치되어 있다 가정 (medical-compliance-tester 이미지)
import psycopg2
from psycopg2.extras import RealDictCursor


def main():
    run_id = os.environ.get('DUMP_RUN_ID', '').strip()
    gcs_path = os.environ.get('DUMP_GCS_PATH', '').strip()
    db_url = os.environ.get('DATABASE_URL', '').strip()

    if not run_id:
        sys.exit('DUMP_RUN_ID 필요')
    if not gcs_path:
        sys.exit('DUMP_GCS_PATH 필요')
    if not db_url:
        sys.exit('DATABASE_URL 필요')

    print(f'connecting to DB...', flush=True)
    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            'SELECT id, run_at, total, passed, failed, env, guideline_version, tester, status, results_json '
            'FROM test_runs WHERE id = %s', (run_id,))
        row = cur.fetchone()
        if not row:
            sys.exit(f'run not found: {run_id}')

    payload = dict(row)
    if payload.get('run_at') and not isinstance(payload['run_at'], str):
        payload['run_at'] = payload['run_at'].isoformat()
    if isinstance(payload.get('results_json'), str):
        payload['results_json'] = json.loads(payload['results_json'])

    print(f'run: id={payload.get("id")}', flush=True)
    print(f'  run_at: {payload.get("run_at")}', flush=True)
    print(f'  total: {payload.get("total")}  passed: {payload.get("passed")}  failed: {payload.get("failed")}', flush=True)
    print(f'  status: {payload.get("status")}  env: {payload.get("env")}', flush=True)
    print(f'  results count: {len(payload.get("results_json") or [])}', flush=True)

    fd, tmp_path = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    size = os.path.getsize(tmp_path)
    print(f'wrote {size} bytes to {tmp_path}', flush=True)

    print(f'uploading to {gcs_path} ...', flush=True)
    # 메타데이터 서버에서 액세스 토큰 획득
    token_req = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'},
    )
    tok = json.loads(urllib.request.urlopen(token_req, timeout=10).read())['access_token']

    # gs://bucket/path → bucket, object
    assert gcs_path.startswith('gs://')
    bucket, obj = gcs_path[5:].split('/', 1)
    upload_url = (
        f'https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o'
        f'?uploadType=media&name={urllib.parse.quote(obj, safe="")}'
    )
    with open(tmp_path, 'rb') as f:
        body = f.read()
    req = urllib.request.Request(upload_url, data=body, method='POST', headers={
        'Authorization': f'Bearer {tok}',
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': str(len(body)),
    })
    resp = urllib.request.urlopen(req, timeout=120)
    print(f'  upload status: {resp.status}', flush=True)
    print('✓ done', flush=True)


if __name__ == '__main__':
    main()
