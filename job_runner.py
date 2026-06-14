#!/usr/bin/env python3
"""
job_runner.py — Cloud Run Job 진입점.

단일 batch 작업을 수행한 뒤 종료한다. Service의 background thread 방식 대비
- task 수명 = 인스턴스 수명 (재시작 0)
- SIGTERM grace period 안에 마지막 flush
- 단일 runId 로 1100건+ 안정 완료

환경변수:
  RUN_ID            : runId (호출자가 미리 생성)
  SCENARIO_IDS_JSON : JSON 배열로 시나리오 ID 전달 (작은 batch 용)
  JOB_PAYLOAD_ID    : DB에 저장된 payload id (큰 batch — env 32KB 한계 회피)
  AUTO_SELECT       : 'all_except_hb' 면 DB에서 HB 제외 enabled 시나리오 전체를 직접 조회
                      (SCENARIO_IDS_JSON/JOB_PAYLOAD_ID 불필요 — Job이 VPC+CloudSQL 연결됨).
                      'all' 이면 HB 포함 enabled 전체.
  RUN_BY            : 실행자 alias
  LABEL             : 라벨 (선택)
  FLUSH_EVERY       : DB 점진 저장 간격 (기본 5 — 실시간 UI polling 위해)
"""

import json
import os
import signal
import sys
from datetime import datetime, timezone

# proxy_server 가 module load 시점에 sys.stdout 을 UTF-8 TextIOWrapper 로 교체한다.
# 여기서는 line_buffering 만 추가로 켜준다 (reconfigure — TextIOWrapper double-wrap 회피).
import db
from batch_executor import BatchExecutor, build_skix_config
# proxy_server 의 모듈 레벨 함수만 가져온다. ProxyHandler 인스턴스는 사용하지 않는다.
from proxy_server import (
    _save_run_to_db, _evaluate_gpt, _evaluate_consultation,
    _evaluate_rubric, _skix_replay,
)

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass


def _job_log(msg):
    """flush=True 로 즉시 출력 — Cloud Logging 실시간 반영용."""
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)


def _auto_select_scenario_ids(mode):
    """DB에서 enabled 시나리오 ID 직접 조회 (Job이 VPC+CloudSQL 연결됨).

    mode='all_except_hb' : HB-/hb- prefix + source='healthbench' 제외 (운영 일반 시나리오)
    mode='all'           : enabled 전체 (HB 포함)

    트리거 측에서 로컬 DB 접속(private IP) 불가할 때 Job 내부에서 추출하는 경로.
    """
    exclude_hb = (mode != 'all')
    data = db.get_scenarios()
    scenarios = data.get('scenarios', []) if isinstance(data, dict) else []
    ids = []
    src_dist = {}
    for s in scenarios:
        if not s.get('enabled', True):
            continue
        sid = s.get('id', '')
        src = (s.get('source') or '')
        if exclude_hb:
            low = sid.lower()
            if low.startswith('hb-') or src == 'healthbench':
                continue
        ids.append(sid)
        src_dist[src or '(none)'] = src_dist.get(src or '(none)', 0) + 1
    ids.sort()
    _job_log(f"[auto-select] mode={mode} → {len(ids)}건 (HB제외={exclude_hb}) source분포={src_dist}")
    return ids


def _load_scenario_ids():
    """env var 또는 DB payload 에서 scenario_ids 로드."""
    auto = os.environ.get('AUTO_SELECT', '').strip().lower()
    if auto in ('all_except_hb', 'all'):
        return _auto_select_scenario_ids(auto), None

    payload_id = os.environ.get('JOB_PAYLOAD_ID', '').strip()
    if payload_id:
        # DB payload 방식 (큰 batch). 미구현 시 명확히 실패.
        if not hasattr(db, 'get_job_payload'):
            raise RuntimeError(
                f"JOB_PAYLOAD_ID={payload_id} 지정됐으나 db.get_job_payload 미구현. "
                f"Risk #4 우회 — job_payloads 테이블 추가 필요."
            )
        payload = db.get_job_payload(payload_id)
        if not payload:
            raise RuntimeError(f"JOB_PAYLOAD_ID={payload_id} payload 없음 (만료 또는 잘못된 id).")
        return payload.get('scenarioIds', []), payload

    sids_json = os.environ.get('SCENARIO_IDS_JSON', '').strip()
    if not sids_json:
        raise RuntimeError(
            "SCENARIO_IDS_JSON / JOB_PAYLOAD_ID / AUTO_SELECT 중 하나가 필요합니다. "
            "(AUTO_SELECT=all_except_hb 로 HB 제외 전체 자동 선택)"
        )
    try:
        sids = json.loads(sids_json)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"SCENARIO_IDS_JSON 파싱 실패: {e}") from e
    if not isinstance(sids, list):
        raise RuntimeError("SCENARIO_IDS_JSON 은 JSON 배열이어야 합니다.")
    return sids, None


# ────────────────────────────────────────────────────────────
# 글로벌 state — SIGTERM 핸들러에서 접근 가능하도록 모듈 레벨
# ────────────────────────────────────────────────────────────
_state = {
    'run_id': None,
    'total': 0,
    'started_at': None,
    'run_by': '',
    'env': 'dev',
    'results': [],
    'passed': 0,
    'failed': 0,
    'errors': 0,
    'last_flush_count': 0,
}


def _flush_to_db(status='running'):
    """현재 state 를 DB 에 저장. status 로 마무리 여부 결정."""
    total = _state['total'] or len(_state['results'])
    completed = len(_state['results'])
    pr = round((_state['passed'] / completed) * 100, 1) if completed else 0.0
    completed_at = datetime.now(timezone.utc).isoformat() if status != 'running' else None
    try:
        _save_run_to_db({
            'runId': _state['run_id'],
            'type': 'job-batch',
            'env': _state['env'],
            'status': status,
            'startedAt': _state['started_at'],
            'completedAt': completed_at,
            'runBy': _state['run_by'],
            'summary': {
                'total': total,
                'passed': _state['passed'],
                'failed': _state['failed'],
                'error': _state['errors'],
                'passRate': pr,
            },
            'results': _state['results'],
        })
        _state['last_flush_count'] = completed
    except Exception as e:
        _job_log(f"[job] DB flush 실패 status={status}: {str(e)[:200]}")


def _make_sigterm_handler():
    def _handler(signum, _frame):
        _job_log(f"SIGTERM 수신 (signum={signum}) — {len(_state['results'])}건 flush 후 종료")
        _flush_to_db(status='cancelled')
        sys.exit(143)
    return _handler


def main():
    run_id = os.environ.get('RUN_ID', '').strip()
    if not run_id:
        # 호출자가 안 주면 자동 생성 (AUTO_SELECT 트리거 등 간편 실행용)
        import uuid as _uuid
        run_id = f"job-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{_uuid.uuid4().hex[:6]}"
        _job_log(f"[job] RUN_ID 미지정 → 자동 생성: {run_id}")

    run_by = os.environ.get('RUN_BY', 'job-runner').strip()
    label = os.environ.get('LABEL', '').strip()
    flush_every = int(os.environ.get('FLUSH_EVERY', '5'))

    scenario_ids, _payload = _load_scenario_ids()
    if not scenario_ids:
        raise RuntimeError("실행할 시나리오 ID가 비어있습니다.")

    settings = db.get_settings()
    openai_key = settings.get('openaiKey', '') or settings.get('openai_api_key', '')
    skix_cfg = build_skix_config(settings, tester_uid=None)

    _state['run_id'] = run_id
    _state['total'] = len(scenario_ids)
    _state['started_at'] = datetime.now(timezone.utc).isoformat()
    _state['run_by'] = run_by
    _state['env'] = skix_cfg.get('current_env', 'dev')

    _job_log(
        f"[job] 시작 run_id={run_id} count={len(scenario_ids)} env={_state['env']} "
        f"run_by={run_by} label={label!r}"
    )

    # 초기 running 상태 DB 저장 (사용자가 폴링 가능하도록)
    _flush_to_db(status='running')

    # SIGTERM 핸들러 등록 (Cloud Run grace period 10초 안에 flush)
    try:
        signal.signal(signal.SIGTERM, _make_sigterm_handler())
        signal.signal(signal.SIGINT, _make_sigterm_handler())
    except Exception as _e:
        _job_log(f"[job] signal handler 등록 실패 (Windows? 무시): {str(_e)[:120]}")

    # API key 사전 검증
    if not skix_cfg.get('api_key'):
        _job_log(f"[job] {_state['env'].upper()} 환경의 API Key 미설정 → error 처리")
        _state['errors'] = len(scenario_ids)
        _flush_to_db(status='completed')
        sys.exit(1)

    # 시나리오 로드
    data = db.get_scenarios()
    scenarios_map = {s['id']: s for s in data.get('scenarios', [])}
    _job_log(f"[job] 시나리오 맵 로드 완료: 전체 {len(scenarios_map)}개 / 요청 {len(scenario_ids)}개")

    executor = BatchExecutor(
        settings=settings,
        openai_key=openai_key,
        skix_config=skix_cfg,
        evaluate_gpt_fn=_evaluate_gpt,
        evaluate_consultation_fn=_evaluate_consultation,
        evaluate_rubric_fn=_evaluate_rubric,
        skix_replay_fn=_skix_replay,
        log_fn=_job_log,
    )

    def on_result(result):
        _state['results'].append(result)
        s = result.get('status')
        if s == 'pass':
            _state['passed'] += 1
        elif s == 'fail':
            _state['failed'] += 1
        elif s == 'error':
            _state['errors'] += 1
        # 점진 저장
        if (len(_state['results']) - _state['last_flush_count']) >= flush_every:
            _flush_to_db(status='running')

    def on_progress(completed, total, current_sid):
        if completed % 10 == 0 or completed == total:
            _job_log(
                f"PROGRESS {completed}/{total} "
                f"pass={_state['passed']} fail={_state['failed']} err={_state['errors']} "
                f"current={current_sid}"
            )

    try:
        summary = executor.run_batch(
            run_id=run_id,
            scenarios_map=scenarios_map,
            scenario_ids=scenario_ids,
            on_progress=on_progress,
            on_result=on_result,
            cancel_check=None,
        )
        # 최종 flush
        _flush_to_db(status='completed')
        _job_log(
            f"[job] DONE run_id={run_id} total={summary['completed']} "
            f"pass={summary['passed']} fail={summary['failed']} err={summary['errors']}"
        )
    except Exception as e:
        _job_log(f"[job] 치명적 오류: {type(e).__name__}: {str(e)[:300]}")
        _flush_to_db(status='completed')
        raise


if __name__ == '__main__':
    main()
