"""1101 시나리오 전체 batch 실행 (v1.5.1 적용본).

운영 DB에서 enabled 시나리오 ID 모두 추출 → batch-runner Cloud Run Job 트리거.

환경변수:
  DATABASE_URL — 운영 DB (자동 주입)
  GCP_PROJECT  — 기본 medical-compliance-tester
  GCP_REGION   — 기본 asia-northeast3
  JOB_NAME     — 기본 batch-runner
  RUN_BY       — 기본 'v151-full-batch'
  LABEL        — 기본 '1101건 전체 batch (v1.5.1 적용)'
"""
import json
import os
import sys
import uuid
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import RealDictCursor


def main():
    db_url = os.environ.get('DATABASE_URL', '').strip()
    project = os.environ.get('GCP_PROJECT', 'medical-compliance-tester').strip()
    region = os.environ.get('GCP_REGION', 'asia-northeast3').strip()
    job_name = os.environ.get('JOB_NAME', 'batch-runner').strip()
    run_by = os.environ.get('RUN_BY', 'v151-full-batch').strip()
    label = os.environ.get('LABEL', '1101건 전체 batch (v1.5.1 적용)').strip()

    if not db_url:
        sys.exit('DATABASE_URL 필요')

    # 1. 시나리오 ID 추출 — HB 제외 (운영 일반 시나리오만)
    exclude_hb = os.environ.get('EXCLUDE_HB', '1').strip() not in ('0', 'false', 'False')
    conn = psycopg2.connect(db_url)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # HB- prefix 또는 source='healthbench' 제외
        where_clause = "(id NOT LIKE 'HB-%' AND id NOT LIKE 'hb-%' AND (source IS NULL OR source != 'healthbench'))" if exclude_hb else "TRUE"
        try:
            cur.execute(f"SELECT id, source FROM scenarios WHERE enabled = TRUE AND {where_clause} ORDER BY id")
            rows = cur.fetchall()
        except Exception:
            conn.rollback()
            try:
                cur.execute(f"SELECT id, source FROM scenarios WHERE {where_clause} ORDER BY id")
                rows = cur.fetchall()
            except Exception:
                conn.rollback()
                # source 컬럼이 없는 경우 — id로만 필터
                fallback_where = "id NOT LIKE 'HB-%' AND id NOT LIKE 'hb-%'" if exclude_hb else "TRUE"
                cur.execute(f"SELECT id FROM scenarios WHERE {fallback_where} ORDER BY id")
                rows = cur.fetchall()
        ids = [r['id'] for r in rows]
        # 디버그: source 분포
        src_dist = {}
        for r in rows:
            s = r.get('source') if isinstance(r, dict) else None
            src_dist[s or '(NULL)'] = src_dist.get(s or '(NULL)', 0) + 1
        print(f'시나리오 ID 수집: {len(ids)}건 (HB 제외={exclude_hb})', flush=True)
        print(f'source 분포: {src_dist}', flush=True)
    if not ids:
        sys.exit('시나리오가 없습니다')

    # 2. runId 생성
    run_id = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
    print(f'runId: {run_id}', flush=True)

    conn.close()
    # 3. job_runner가 자동으로 DB row 생성

    # 4. Cloud Run Job 트리거
    from google.cloud import run_v2
    from google.cloud.run_v2 import types as run_types

    sids_json = json.dumps(ids, ensure_ascii=False)
    print(f'SCENARIO_IDS_JSON 길이: {len(sids_json)} 문자', flush=True)
    if len(sids_json) > 30000:
        print('⚠ 30K 초과 — 환경변수 한도 위험 (32K). GCS payload 패턴 권장.', flush=True)

    client = run_v2.JobsClient()
    job_path = f"projects/{project}/locations/{region}/jobs/{job_name}"
    env_vars = [
        run_types.EnvVar(name='RUN_ID', value=run_id),
        run_types.EnvVar(name='SCENARIO_IDS_JSON', value=sids_json),
        run_types.EnvVar(name='RUN_BY', value=run_by),
        run_types.EnvVar(name='LABEL', value=label),
    ]
    overrides = run_types.RunJobRequest.Overrides(
        container_overrides=[
            run_types.RunJobRequest.Overrides.ContainerOverride(env=env_vars)
        ]
    )
    request = run_types.RunJobRequest(name=job_path, overrides=overrides)
    operation = client.run_job(request=request)
    print(f'✓ batch-runner Job 트리거 완료', flush=True)
    print(f'  runId: {run_id}', flush=True)
    print(f'  시나리오: {len(ids)}건', flush=True)
    print(f'  label: {label}', flush=True)


if __name__ == '__main__':
    main()
