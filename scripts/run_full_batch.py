"""
PROD 1100개 시나리오 전체 배치 실행 + 자동 모니터링.

- POST /api/test/batch로 1100개 시작
- /api/test/status로 30초 간격 폴링
- 진행 상황을 stdout으로 line-buffered 출력 (Monitor 감지용)
- 5분마다 SUMMARY 라인
- 정체 감지(120초간 진행 없음) 시 경고
- 완료 시 최종 통계 출력

사용:
  ADMIN_PW='123Qwer!' python scripts/run_full_batch.py
"""
import io
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import requests

PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'
POLL_INTERVAL = 30        # 폴링 간격 (초)
STALL_TIMEOUT = 180       # 진행 없으면 경고 (초)
LOG_EVERY = 1             # 폴링마다 로그
SUMMARY_EVERY = 300       # 5분마다 SUMMARY 출력

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

def main():
    admin_pw = os.environ.get('ADMIN_PW', '')
    if not admin_pw:
        log("[ERROR] ADMIN_PW 환경변수 필요")
        sys.exit(1)

    session = requests.Session()

    log("=" * 70)
    log("PROD 1100개 배치 테스트 실행 + 자동 모니터링 시작")
    log(f"PROD URL: {PROD_URL}")
    log("=" * 70)

    # 1) admin 로그인
    log("[1/4] admin 로그인...")
    r = session.post(f"{PROD_URL}/api/auth/login",
                     json={'id': 'admin', 'password': admin_pw}, timeout=15)
    r.raise_for_status()
    if not r.json().get('isAdmin'):
        log(f"[ERROR] admin 로그인 실패: {r.json()}")
        sys.exit(1)
    log("  OK")

    # 2) 시나리오 1100개 ID 수집
    log("[2/4] 시나리오 ID 수집...")
    r = session.get(f"{PROD_URL}/api/scenarios", timeout=30)
    r.raise_for_status()
    scenarios = r.json().get('scenarios', [])
    scenario_ids = [s['id'] for s in scenarios if s.get('id')]
    log(f"  총 {len(scenario_ids)}개 시나리오")
    if len(scenario_ids) == 0:
        log("[ERROR] 시나리오 없음")
        sys.exit(1)

    # source/category 통계
    from collections import Counter
    src = Counter(s.get('source', 'manual') for s in scenarios)
    cat = Counter(s.get('category', '미분류') for s in scenarios)
    log(f"  source별: {dict(src)}")
    log(f"  카테고리 수: {len(cat)}")

    # 3) 배치 시작
    log(f"[3/4] 배치 실행 시작 ({len(scenario_ids)}개)...")
    started_at = time.time()
    r = session.post(f"{PROD_URL}/api/test/batch",
                     json={'scenarioIds': scenario_ids}, timeout=30)
    if r.status_code != 200:
        log(f"[ERROR] 배치 시작 실패: HTTP {r.status_code} {r.text[:500]}")
        sys.exit(1)
    data = r.json()
    run_id = data.get('runId', '')
    if not run_id:
        log(f"[ERROR] runId 없음: {data}")
        sys.exit(1)
    log(f"  runId: {run_id}")
    log(f"  메시지: {data.get('message', '')}")

    # 4) 진행 모니터링
    log(f"[4/4] 모니터링 시작 (폴링 간격 {POLL_INTERVAL}s)")
    log("")
    log("=" * 70)
    log("PROGRESS MONITORING")
    log("=" * 70)

    last_completed = -1
    last_progress_time = time.time()
    last_summary_time = time.time()
    poll_count = 0
    stall_warned = False

    while True:
        time.sleep(POLL_INTERVAL)
        poll_count += 1

        try:
            r = session.get(f"{PROD_URL}/api/test/status/{run_id}", timeout=15)
            if r.status_code != 200:
                log(f"  [POLL #{poll_count}] HTTP {r.status_code} {r.text[:200]}")
                continue
            status = r.json()
        except Exception as e:
            log(f"  [POLL #{poll_count}] 폴링 오류: {str(e)[:200]}")
            continue

        completed = status.get('completed', 0)
        total = status.get('total', len(scenario_ids))
        passed = status.get('passed', 0)
        failed = status.get('failed', 0)
        errors = status.get('errors', 0)
        run_status = status.get('status', 'unknown')
        current = status.get('current', '')

        elapsed = time.time() - started_at
        pct = (completed / total * 100) if total > 0 else 0

        # 진행 라인 (Monitor에서 grep)
        if completed != last_completed:
            last_completed = completed
            last_progress_time = time.time()
            stall_warned = False
            eta_sec = ((elapsed / completed) * (total - completed)) if completed > 0 else 0
            eta_min = int(eta_sec / 60)
            log(f"PROGRESS {completed}/{total} ({pct:.1f}%) "
                f"pass={passed} fail={failed} err={errors} "
                f"elapsed={int(elapsed/60)}m ETA={eta_min}m"
                + (f" current={current[:50]}" if current else ""))
        else:
            # 진행 없음
            stall = time.time() - last_progress_time
            if stall > STALL_TIMEOUT and not stall_warned:
                log(f"STALL_WARN 진행 없음 {int(stall)}s @ {completed}/{total}")
                stall_warned = True

        # SUMMARY (5분마다)
        if time.time() - last_summary_time >= SUMMARY_EVERY:
            last_summary_time = time.time()
            log(f"SUMMARY [+{int(elapsed/60)}m] {completed}/{total} ({pct:.1f}%) "
                f"pass_rate={(passed/completed*100 if completed > 0 else 0):.1f}% "
                f"errors={errors}")

        # 완료 체크
        if run_status == 'completed' or completed >= total:
            log("")
            log("=" * 70)
            log("BATCH COMPLETED")
            log("=" * 70)
            log(f"총 시간: {int(elapsed/60)}분 {int(elapsed%60)}초")
            log(f"전체: {total}개")
            log(f"통과: {passed} ({passed/total*100:.1f}%)")
            log(f"실패: {failed} ({failed/total*100:.1f}%)")
            log(f"오류: {errors} ({errors/total*100:.1f}%)")
            log(f"평균 시간/시나리오: {elapsed/total:.2f}s")
            log(f"runId: {run_id}")
            log("")
            log(f"이력 확인: {PROD_URL}/history (runId={run_id})")

            # 최종 상태를 JSON 파일로 저장
            try:
                out = Path(__file__).resolve().parent / f"batch_result_{run_id}.json"
                with open(out, 'w', encoding='utf-8') as f:
                    json.dump({
                        'runId': run_id,
                        'total': total,
                        'passed': passed,
                        'failed': failed,
                        'errors': errors,
                        'elapsed_seconds': elapsed,
                        'elapsed_minutes': elapsed / 60,
                        'avg_per_scenario': elapsed / total if total else 0,
                        'completed_at': datetime.now(timezone.utc).isoformat(),
                    }, f, ensure_ascii=False, indent=2)
                log(f"결과 저장: {out}")
            except Exception as e:
                log(f"  [WARN] 결과 저장 실패: {e}")
            break

        # cancelled 체크
        if run_status == 'cancelled':
            log(f"BATCH_CANCELLED status={run_status}")
            break

    log("DONE")

if __name__ == '__main__':
    main()
