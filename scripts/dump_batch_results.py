"""특정 runId의 batch 결과를 GCS에 dump.

env:
  DATABASE_URL — 운영 DB
  RUN_ID — 대상 runId
  OUT_GCS_PATH — gs://bucket/path.json
"""
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

import psycopg2
from psycopg2.extras import RealDictCursor


def upload(local_path, gcs_path):
    token_req = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'},
    )
    tok = json.loads(urllib.request.urlopen(token_req, timeout=10).read())['access_token']
    bucket, obj = gcs_path[5:].split('/', 1)
    upload_url = (
        f'https://storage.googleapis.com/upload/storage/v1/b/{bucket}/o'
        f'?uploadType=media&name={urllib.parse.quote(obj, safe="")}'
    )
    with open(local_path, 'rb') as f:
        body = f.read()
    req = urllib.request.Request(upload_url, data=body, method='POST', headers={
        'Authorization': f'Bearer {tok}',
        'Content-Type': 'application/json; charset=utf-8',
        'Content-Length': str(len(body)),
    })
    return urllib.request.urlopen(req, timeout=180).status


def main():
    db_url = os.environ.get('DATABASE_URL', '').strip()
    run_id = os.environ.get('RUN_ID', '').strip()
    out_gcs = os.environ.get('OUT_GCS_PATH', '').strip()
    if not db_url or not run_id or not out_gcs:
        sys.exit('DATABASE_URL, RUN_ID, OUT_GCS_PATH 필요')

    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM test_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
        if not row:
            sys.exit(f'run {run_id} 없음')
    # JSONB 컬럼들은 이미 dict
    payload = {
        'runId': run_id,
        'type': row.get('type'),
        'env': row.get('env'),
        'status': row.get('status'),
        'startedAt': str(row.get('started_at')) if row.get('started_at') else None,
        'completedAt': str(row.get('completed_at')) if row.get('completed_at') else None,
        'runBy': row.get('run_by'),
        'label': row.get('label'),
        'summary': row.get('summary_json') or row.get('summary'),
        'results': row.get('results_json') or row.get('results') or [],
    }
    n = len(payload['results']) if isinstance(payload['results'], list) else 0
    print(f'결과 {n}건 추출', flush=True)

    fd, tmp = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)
    sz = os.path.getsize(tmp)
    print(f'파일 크기: {sz/1024/1024:.1f} MB', flush=True)
    print(f'업로드: {out_gcs}', flush=True)
    print(f'  status: {upload(tmp, out_gcs)}', flush=True)
    print('✓ done', flush=True)


if __name__ == '__main__':
    main()
