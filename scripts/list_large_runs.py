"""Cloud Run Job: total >= MIN_TOTAL 인 완료 배치 목록 + (선택) 결과 덤프.

환경변수:
  MIN_TOTAL         — 최소 시나리오 수 (기본 1100)
  LIST_GCS_PATH     — gs://bucket/path/list.json (목록 저장)
  DUMP_ALL          — '1' 이면 각 run 의 results_json 도 같이 덤프
  DUMP_GCS_PREFIX   — DUMP_ALL=1 일 때 결과 저장 prefix (예: gs://bucket/dumps/)
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


def upload(local_path, gcs_path):
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
    resp = urllib.request.urlopen(req, timeout=180)
    return resp.status


def main():
    min_total = int(os.environ.get('MIN_TOTAL', '1100'))
    list_gcs = os.environ.get('LIST_GCS_PATH', '').strip()
    dump_all = os.environ.get('DUMP_ALL', '').strip() == '1'
    dump_prefix = os.environ.get('DUMP_GCS_PREFIX', '').strip()
    db_url = os.environ.get('DATABASE_URL', '').strip()

    if not db_url:
        sys.exit('DATABASE_URL 필요')
    if not list_gcs:
        sys.exit('LIST_GCS_PATH 필요')
    if dump_all and not dump_prefix:
        sys.exit('DUMP_ALL=1 일 때 DUMP_GCS_PREFIX 필요')

    print(f'쿼리: total >= {min_total} AND status = completed', flush=True)
    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            "SELECT id, run_at, total, passed, failed, env, status, tester "
            "FROM test_runs "
            "WHERE total >= %s AND status = 'completed' "
            "ORDER BY run_at DESC",
            (min_total,)
        )
        rows = cur.fetchall()
        print(f'발견: {len(rows)}건', flush=True)

        out_list = []
        for r in rows:
            rr = dict(r)
            if rr.get('run_at') and not isinstance(rr['run_at'], str):
                rr['run_at'] = rr['run_at'].isoformat()
            out_list.append(rr)
            print(f"  {rr.get('id')}  total={rr.get('total')}  pass={rr.get('passed')}/{rr.get('failed')}  env={rr.get('env')}  at={(rr.get('run_at') or '')[:19]}", flush=True)

        # 목록 업로드
        fd, tmp = tempfile.mkstemp(suffix='.json')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(out_list, f, ensure_ascii=False)
        print(f'list upload: {list_gcs}', flush=True)
        print(f'  status: {upload(tmp, list_gcs)}', flush=True)

        # 각 run 덤프
        if dump_all:
            for r in rows:
                run_id = r['id']
                print(f'\ndump: {run_id}', flush=True)
                cur.execute(
                    'SELECT id, run_at, total, passed, failed, env, guideline_version, tester, status, results_json '
                    'FROM test_runs WHERE id = %s', (run_id,)
                )
                row = cur.fetchone()
                if not row:
                    continue
                payload = dict(row)
                if payload.get('run_at') and not isinstance(payload['run_at'], str):
                    payload['run_at'] = payload['run_at'].isoformat()
                if isinstance(payload.get('results_json'), str):
                    payload['results_json'] = json.loads(payload['results_json'])
                fd2, tmp2 = tempfile.mkstemp(suffix='.json')
                with os.fdopen(fd2, 'w', encoding='utf-8') as f:
                    json.dump(payload, f, ensure_ascii=False)
                gcs_target = dump_prefix.rstrip('/') + '/' + run_id + '.json'
                print(f'  → {gcs_target} (size {os.path.getsize(tmp2)} bytes)', flush=True)
                print(f'  status: {upload(tmp2, gcs_target)}', flush=True)

    print('\n✓ done', flush=True)


if __name__ == '__main__':
    main()
