# Cloud Run Jobs 이전 — 작업 계획서

> 1100건+ 대량 배치 처리를 안정적으로 완료하기 위해 Cloud Run Service의 background thread 방식을 Cloud Run Jobs로 이전한다.

## 배경 — 왜 이전이 필요한가

### 현재 문제 (Service에서 background thread 사용)
- 인스턴스 lifecycle 비결정적 (idle/health/replacement)
- 1100건 단일 배치 시 인스턴스 cancelled 빈발
  - 1차 1100건: 727건 처리 후 cancelled (~3.5시간)
  - 2차 1001건: 49건 처리 후 cancelled (~10분)
  - 새 1차 1100건: 99건 처리 후 cancelled (~24분)
- 4 shard 분산으로 우회 중 (61분 완료) — 그러나 사용자에게는 6개 runId 분산

### 기대 효과
- task 수명 = 인스턴스 수명 (재시작 0)
- 단일 runId로 1100건+ 안정 완료
- 비용 절감 (idle 시간 0원)
- 운영 부담 감소 (재시도/누락 추적 코드 불필요)

---

## Phase 1 — BatchExecutor 분리 + Job 진입점 (2-3시간)

### 1.1 `batch_executor.py` 신규 — 재사용 가능한 batch 실행 모듈

**현재 위치**: `proxy_server.py` `ProxyHandler._batch_run()` + `execute_single()` 내부

**분리 방식**:
```python
# batch_executor.py
class BatchExecutor:
    """Service와 Job 둘 다 사용하는 batch 실행 로직."""

    def __init__(self, db_module, settings, openai_key, skix_config, log_fn=print):
        self.db = db_module
        self.settings = settings
        self.openai_key = openai_key
        self.gpt_model = settings.get('openaiModel', 'gpt-4o-mini')
        self.skix = skix_config  # {api_url, api_key, tenant_domain, api_uid, graph_type}
        self.log = log_fn

    def execute_single(self, sid, sc, ctx_settings=None) -> dict:
        """단일 시나리오 실행 — SKIX 호출 + LLM 평가 + 에러 추적."""
        # 현재 proxy_server.py execute_single 로직 그대로 (line 2397~2620)
        ...

    def run_batch(
        self,
        run_id: str,
        scenario_ids: list,
        on_progress=None,        # callback(completed, total, current_sid)
        on_result=None,          # callback(result_dict) — 점진 저장용
        max_workers=10,
        chunk_size=50,
        cancel_check=None,       # callable returning bool
    ) -> dict:
        """청크 기반 병렬 실행. on_result 콜백으로 점진 DB 저장 가능."""
        ...
```

**핵심**: 기존 service의 `_run_batch`가 BatchExecutor를 사용하도록 변경.

### 1.2 `job_runner.py` 신규 — Cloud Run Job 진입점

```python
"""Cloud Run Job 진입점 — 단일 batch 작업 수행 후 종료.

환경변수:
  RUN_ID            : 새 또는 기존 runId
  SCENARIO_IDS_JSON : JSON 배열로 시나리오 ID 전달
  RUN_BY            : 실행자 alias
  LABEL             : 라벨 (선택)
"""
import os, sys, json, signal, io
from datetime import datetime, timezone
import db
from batch_executor import BatchExecutor
from proxy_server import (
    _save_run_to_db, _evaluate_gpt, _evaluate_consultation,
    _check_compliance,
)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

def main():
    run_id = os.environ['RUN_ID']
    sids = json.loads(os.environ['SCENARIO_IDS_JSON'])
    run_by = os.environ.get('RUN_BY', 'system')

    settings = db.get_settings()
    skix_cfg = _build_skix_config(settings)
    openai_key = settings.get('openaiKey', '')

    executor = BatchExecutor(db, settings, openai_key, skix_cfg, log_fn=print)

    # 초기 DB 저장 (running 상태)
    now = datetime.now(timezone.utc).isoformat()
    _save_run_to_db({
        'runId': run_id, 'type': 'job-batch', 'env': settings.get('currentEnv', 'prod'),
        'status': 'running', 'startedAt': now, 'completedAt': None, 'runBy': run_by,
        'summary': {'total': len(sids), 'passed': 0, 'failed': 0, 'error': 0, 'passRate': 0},
        'results': [],
    })

    # 점진 저장 콜백
    state = {'passed': 0, 'failed': 0, 'errors': 0, 'results': []}
    def save_chunk(result):
        state['results'].append(result)
        status = result.get('status')
        if status == 'pass': state['passed'] += 1
        elif status == 'fail': state['failed'] += 1
        elif status == 'error': state['errors'] += 1
        # 매 50개마다 DB flush
        if len(state['results']) % 50 == 0:
            _flush_to_db(run_id, state, run_by, settings)

    def progress(c, t, current=''):
        print(f'PROGRESS {c}/{t} pass={state["passed"]} fail={state["failed"]} err={state["errors"]} current={current}', flush=True)

    # SIGTERM 핸들러 (Cloud Run grace period 10초 안에 마지막 flush)
    def shutdown(signum, frame):
        print(f'SIGTERM received — flushing {len(state["results"])} results...', flush=True)
        _flush_to_db(run_id, state, run_by, settings, status='cancelled')
        sys.exit(0)
    signal.signal(signal.SIGTERM, shutdown)

    executor.run_batch(run_id, sids, on_progress=progress, on_result=save_chunk)

    # 최종 flush
    _flush_to_db(run_id, state, run_by, settings, status='completed')
    print(f'DONE run_id={run_id} total={len(state["results"])} pass={state["passed"]} fail={state["failed"]} err={state["errors"]}', flush=True)


def _flush_to_db(run_id, state, run_by, settings, status='running'):
    total = len(state['results'])
    _save_run_to_db({
        'runId': run_id, 'type': 'job-batch', 'env': settings.get('currentEnv', 'prod'),
        'status': status,
        'startedAt': state.get('startedAt'),
        'completedAt': datetime.now(timezone.utc).isoformat() if status != 'running' else None,
        'runBy': run_by,
        'summary': {
            'total': state.get('total', total),
            'passed': state['passed'],
            'failed': state['failed'],
            'error': state['errors'],
            'passRate': round((state['passed'] / total) * 100, 1) if total else 0,
        },
        'results': state['results'],
    })


def _build_skix_config(settings):
    env = settings.get('currentEnv', 'prod')
    envs = settings.get('environments', {})
    cfg = envs.get(env, {})
    return {
        'api_url': cfg.get('apiUrl', ''),
        'api_key': cfg.get('xApiKey', ''),
        'tenant_domain': cfg.get('xTenantDomain', ''),
        'api_uid': cfg.get('xApiUid', ''),
        'graph_type': settings.get('graphType', 'ORCHESTRATED_HYBRID_SEARCH'),
    }


if __name__ == '__main__':
    main()
```

---

## Phase 2 — Dockerfile + 이미지 빌드 (1시간)

### 2.1 단일 이미지에 Service + Job 모드 통합

```dockerfile
# Dockerfile (수정)
FROM python:3.12-slim
WORKDIR /app

# 의존성 + 코드 복사
COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt
COPY . /app/

# entrypoint shell
COPY entrypoint.sh /app/
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
```

```bash
# entrypoint.sh
#!/bin/sh
if [ "$RUN_MODE" = "job" ]; then
    exec python /app/job_runner.py
else
    exec python /app/proxy_server.py --port "${PORT:-8080}"
fi
```

기존 Dockerfile의 CMD/ENTRYPOINT 라인 교체. Cloud Run Service는 RUN_MODE 환경변수 없음 = service 모드.

---

## Phase 3 — Job 배포 + 트리거 (2시간)

### 3.1 `deploy-job.ps1` 신규

```powershell
param(
    [string]$ProjectId = "medical-compliance-tester",
    [string]$Region = "asia-northeast3",
    [string]$JobName = "batch-runner",
    [string]$ServiceName = "medical-compliance-tester",
    [string]$SqlInstance = "medical-db",
    [string]$DbPassword = ""
)

# DB 비밀번호 로직 (deploy.ps1과 동일)
if (-not $DbPassword) { $DbPassword = $env:DB_PASSWORD }
if (-not $DbPassword) {
    $DbPassword = gcloud secrets versions access latest --secret=db-password --project=$ProjectId 2>$null
}

$SqlConnection = "${ProjectId}:${Region}:${SqlInstance}"
$DatabaseUrl = "postgresql://app_user:${DbPassword}@/medical_app?host=/cloudsql/${SqlConnection}"

# 이미지는 service deploy에서 빌드된 것 재사용
$ImageUri = "gcr.io/$ProjectId/$ServiceName"

# Job 존재 확인 + create/update
$exists = gcloud run jobs describe $JobName --region $Region 2>$null
$Action = if ($exists) { 'update' } else { 'create' }

gcloud run jobs $Action $JobName `
    --image $ImageUri `
    --region $Region `
    --memory 8Gi --cpu 4 `
    --task-timeout 86400 `
    --max-retries 0 `
    --parallelism 1 `
    --task-count 1 `
    --set-env-vars "RUN_MODE=job,DATABASE_URL=$DatabaseUrl" `
    --add-cloudsql-instances $SqlConnection `
    --vpc-connector medical-connector `
    --vpc-egress all-traffic `
    --execution-environment gen2

Write-Host "Job '$JobName' 배포 완료." -ForegroundColor Green
Write-Host "trigger: gcloud run jobs execute $JobName --region $Region --update-env-vars RUN_ID=...,SCENARIO_IDS_JSON='[...]'"
```

### 3.2 Service Account 권한

`batch-runner@PROJECT.iam.gserviceaccount.com` 생성:
- `roles/cloudsql.client`
- `roles/secretmanager.secretAccessor`
- `roles/run.invoker` (자기 자신)

---

## Phase 4 — Service ↔ Job 통합 (2-3시간)

### 4.1 Job 트리거 함수 (`proxy_server.py`)

```python
def _trigger_job_run(self, scenario_ids, run_by='', label=''):
    """Cloud Run Job 비동기 트리거. 즉시 runId 반환."""
    import secrets, subprocess
    run_id = f"job-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(3)}"
    now = datetime.now(timezone.utc).isoformat()

    # DB에 즉시 running 상태 저장 (사용자가 폴링 가능하도록)
    _save_run_to_db({
        'runId': run_id, 'type': 'job-batch', 'env': db.get_settings().get('currentEnv', 'prod'),
        'status': 'running', 'startedAt': now, 'completedAt': None, 'runBy': run_by,
        'summary': {'total': len(scenario_ids), 'passed': 0, 'failed': 0, 'error': 0, 'passRate': 0},
        'results': [],
    })

    # Job 트리거 (subprocess로 비동기)
    env_vars = ','.join([
        f'RUN_ID={run_id}',
        f'SCENARIO_IDS_JSON={json.dumps(scenario_ids)}',  # JSON escape 주의
        f'RUN_BY={run_by}',
        f'LABEL={label}',
    ])

    try:
        subprocess.Popen([
            'gcloud', 'run', 'jobs', 'execute', 'batch-runner',
            '--region', 'asia-northeast3',
            '--update-env-vars', env_vars,
            '--async',
        ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        ProxyHandler._add_log(f"[job] trigger 실패: {e}")
        # DB 상태를 error로 업데이트
        return self._send_error(500, f'Job 트리거 실패: {e}')

    ProxyHandler._add_log(f"[job] 트리거 OK runId={run_id} count={len(scenario_ids)}")
    self._send_json(202, {
        'runId': run_id, 'status': 'queued', 'type': 'job-batch',
        'total': len(scenario_ids),
        'message': f'{len(scenario_ids)}개 시나리오 Job으로 시작됨',
    })
```

**더 안정적 방법** — `google-api-python-client` 라이브러리 사용 (subprocess 없이):
```python
from google.cloud import run_v2
client = run_v2.JobsClient()
job_name = f"projects/{PROJECT}/locations/{REGION}/jobs/batch-runner"
client.run_job(name=job_name, overrides={'container_overrides': [{'env': [...]}]})
```

### 4.2 라우팅 분기 (POST /api/test/batch)

```python
# proxy_server.py 안의 _batch_run 함수 시작 부분
if len(scenario_ids) >= 500 or payload.get('useJob'):
    return self._trigger_job_run(scenario_ids, self._get_alias(), payload.get('label', ''))
# 그 외엔 기존 background thread 사용
```

### 4.3 Cancel 통합

```python
# POST /api/test/cancel/{runId}
def _cancel_batch(self, run_id):
    run = db.get_test_run(run_id)
    if run and run.get('type') == 'job-batch':
        # Job execution 찾아서 cancel
        import subprocess
        subprocess.Popen([
            'gcloud', 'run', 'jobs', 'executions', 'cancel',
            '--filter', f'metadata.labels."run.googleapis.com/runId"={run_id}',
            '--region', 'asia-northeast3',
        ])
    else:
        # 기존 background thread cancel
        ProxyHandler._cancel_flags[run_id] = True
    self._send_json(200, {'success': True})
```

---

## Phase 5 — 운영/모니터링 (1시간 + 지속)

### 5.1 진행 상황 추적

- 사용자는 기존 `/api/test/status/{runId}` 또는 `/api/history/{runId}` 폴링
- Job은 점진 저장(매 50개) → 사용자가 history.summary로 실시간 진행 확인
- `/api/test/status`는 job-batch면 history 데이터 반환

### 5.2 Cloud Logging 통합

```python
# /api/logs?source=job 옵션
def _get_job_logs(self, run_id):
    """Cloud Logging에서 특정 run_id의 job 로그 조회."""
    from google.cloud import logging as cloud_logging
    client = cloud_logging.Client()
    filter_ = f'resource.type="cloud_run_job" AND textPayload:"{run_id}"'
    entries = list(client.list_entries(filter_=filter_, page_size=200))
    return [{'time': e.timestamp.isoformat(), 'text': e.payload} for e in entries]
```

### 5.3 비용 모니터링

- Cloud Run Jobs 가격: vCPU $0.024/시간, 메모리 $0.0025/GiB/시간
- 1100건 배치 (8Gi × 4 vCPU × 1시간) ≈ **$0.18~0.25**
- 월 50회 실행 시 약 $10 (현재 service idle 비용보다 저렴)

---

## ⚠ 위험 요소 + 완화

| # | 위험 | 영향 | 완화 |
|---|---|---|---|
| 1 | `_batch_run` 로직 분리 복잡도 | 중 | 단위 테스트 + 기존 service 유지 |
| 2 | Service Account 권한 부족 | 중 | 사전 IAM 설정 + 권한 검증 |
| 3 | Job 트리거 latency (2-5초) | 낮 | UI에 "큐잉됨" 메시지 |
| 4 | SCENARIO_IDS_JSON 환경변수 크기 한계 (32KB) | 중 | 1100건 ID 약 50KB → Cloud Storage URI로 전달 또는 DB에서 조회 |
| 5 | DB connection 풀 | 낮 | psycopg2 단일 연결 OK |
| 6 | OpenAI quota (기존과 동일) | 중 | 사전 충전 확인 |

### Risk #4 우회 — 환경변수 대신 DB 사용

```python
# Service 측: scenario_ids를 임시 테이블에 저장
job_payload_id = secrets.token_hex(8)
db.save_job_payload(job_payload_id, {'scenarioIds': scenario_ids, 'runBy': run_by})

# 환경변수에는 ID만 전달
env_vars = f'RUN_ID={run_id},JOB_PAYLOAD_ID={job_payload_id}'

# Job 측: payload_id로 DB에서 조회
payload = db.get_job_payload(os.environ['JOB_PAYLOAD_ID'])
sids = payload['scenarioIds']
```

`job_payloads` 테이블 추가 (TTL 24시간).

---

## 📅 작업 일정 (1일)

| 단계 | 작업 | 시간 | 산출물 |
|---|---|---|---|
| 1 | BatchExecutor 분리 + job_runner.py | 2h | `batch_executor.py`, `job_runner.py` |
| 2 | Dockerfile/entrypoint 수정 + 이미지 빌드 | 1h | 단일 이미지 (service + job) |
| 3 | deploy-job.ps1 + Service Account | 1h | Cloud Run Jobs 활성화 |
| 4 | Service 통합 (트리거/상태/cancel) | 2h | API 라우팅 분기 |
| 5 | DEV 통합 테스트 (50건 + 1100건) | 2h | 검증 완료 |
| 6 | PROD 배포 + 모니터링 | 1h | 운영 시작 |

## 🎯 검증 체크리스트

- [ ] BatchExecutor 단위 동작 (mock SKIX/OpenAI)
- [ ] job_runner.py 로컬 실행 (`RUN_MODE=job python job_runner.py`)
- [ ] Docker 이미지 빌드 + 두 모드 동작
- [ ] Cloud Run Job 50건 테스트 (5-10분)
- [ ] Cloud Run Job 1100건 테스트 (60-90분) — 인스턴스 재시작 없음
- [ ] Service `useJob=true` 트리거 → 단일 runId
- [ ] SIGTERM grace period 결과 저장
- [ ] Cancel API 동작
- [ ] 비용 모니터링 (예상치 대비)

## 시작 시점

DEV 환경에서 영향 없이 별도 트랙으로 개발 가능. PROD service는 그대로 유지.
