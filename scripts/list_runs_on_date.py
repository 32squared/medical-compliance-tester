"""Cloud Run Job 에서 실행 — 특정 날짜의 test_runs 목록을 GCS 에 덤프.

환경변수:
  TARGET_DATE       — 'YYYY-MM-DD' (예: 2026-05-21)
  LIST_GCS_PATH     — gs://bucket/path/list.json
  DUMP_RUN_ID       — (선택) 특정 run_id 지정 시 그 run의 results 도 같이 덤프
  DUMP_GCS_PATH     — (DUMP_RUN_ID 있을 때) results 덤프 위치
  DATABASE_URL      — Cloud Run env 자동 주입
"""
import json
import os
import sys
import tempfile
import urllib.parse
import urllib.request

import psycopg2
from psycopg2.extras import RealDictCursor


def upload_to_gcs(local_path, gcs_path):
    token_req = urllib.request.Request(
        'http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token',
        headers={'Metadata-Flavor': 'Google'},
    )
    tok = json.loads(urllib.request.urlopen(token_req, timeout=10).read())['access_token']
    assert gcs_path.startswith('gs://')
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
    resp = urllib.request.urlopen(req, timeout=120)
    return resp.status


def main():
    target_date = os.environ.get('TARGET_DATE', '').strip()
    list_gcs = os.environ.get('LIST_GCS_PATH', '').strip()
    dump_run_id = os.environ.get('DUMP_RUN_ID', '').strip()
    dump_gcs = os.environ.get('DUMP_GCS_PATH', '').strip()
    db_url = os.environ.get('DATABASE_URL', '').strip()

    if not target_date and not dump_run_id:
        sys.exit('TARGET_DATE 또는 DUMP_RUN_ID 필요')
    if not db_url:
        sys.exit('DATABASE_URL 필요')

    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        if target_date and list_gcs:
            print(f'쿼리: run_at >= {target_date} AND run_at < {target_date} + 1 day', flush=True)
            cur.execute(
                "SELECT id, run_at, total, passed, failed, env, status, tester "
                "FROM test_runs "
                "WHERE run_at::date = %s::date "
                "ORDER BY run_at DESC",
                (target_date,)
            )
            rows = cur.fetchall()
            print(f'발견: {len(rows)}건', flush=True)
            out = []
            for r in rows:
                rr = dict(r)
                if rr.get('run_at') and not isinstance(rr['run_at'], str):
                    rr['run_at'] = rr['run_at'].isoformat()
                out.append(rr)
                print(f"  {rr.get('id')}  total={rr.get('total')}  status={rr.get('status')}  pass={rr.get('passed')}/fail={rr.get('failed')}  at={rr.get('run_at','')[:19]}", flush=True)
            fd, tmp = tempfile.mkstemp(suffix='.json')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(out, f, ensure_ascii=False)
            print(f'list upload: {list_gcs}', flush=True)
            print(f'status: {upload_to_gcs(tmp, list_gcs)}', flush=True)

        if dump_run_id and dump_gcs:
            cur.execute(
                'SELECT id, run_at, total, passed, failed, env, guideline_version, tester, status, results_json '
                'FROM test_runs WHERE id = %s', (dump_run_id,)
            )
            row = cur.fetchone()
            if not row:
                print(f'run not found: {dump_run_id}', flush=True)
            else:
                payload = dict(row)
                if payload.get('run_at') and not isinstance(payload['run_at'], str):
                    payload['run_at'] = payload['run_at'].isoformat()
                if isinstance(payload.get('results_json'), str):
                    payload['results_json'] = json.loads(payload['results_json'])
                fd, tmp = tempfile.mkstemp(suffix='.json')
                with os.fdopen(fd, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False)
                print(f'run dump: total={payload.get("total")}, results={len((payload.get("results_json") or []))}', flush=True)
                print(f'dump upload: {dump_gcs}', flush=True)
                print(f'status: {upload_to_gcs(tmp, dump_gcs)}', flush=True)

    print('✓ done', flush=True)


if __name__ == '__main__':
    main()
