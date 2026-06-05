"""기존 진행 중 배치의 진행 모니터링 (runId만 받음)."""
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
POLL_INTERVAL = 30
STALL_TIMEOUT = 300        # 진행 없으면 경고 (5분)
SUMMARY_EVERY = 300        # 5분마다 SUMMARY

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

def main():
    if len(sys.argv) < 2:
        log("[ERROR] usage: monitor_batch.py <runId>")
        sys.exit(1)
    run_id = sys.argv[1]
    admin_pw = os.environ.get('ADMIN_PW', '')

    session = requests.Session()
    if admin_pw:
        r = session.post(f"{PROD_URL}/api/auth/login",
                         json={'id': 'admin', 'password': admin_pw}, timeout=15)
        if not r.ok or not r.json().get('isAdmin'):
            log(f"[WARN] admin 로그인 실패, status endpoint는 인증 없이도 가능할 수 있음")

    log(f"모니터링 시작 — runId: {run_id}")
    log(f"폴링 간격: {POLL_INTERVAL}s")
    log("=" * 70)

    started_at = time.time()
    last_completed = -1
    last_progress_time = time.time()
    last_summary_time = time.time()
    poll_count = 0
    stall_warned = False
    total_initial = None

    while True:
        time.sleep(POLL_INTERVAL)
        poll_count += 1

        try:
            r = session.get(f"{PROD_URL}/api/test/status/{run_id}", timeout=15)
            if r.status_code != 200:
                log(f"[POLL #{poll_count}] HTTP {r.status_code} {r.text[:200]}")
                if r.status_code == 404:
                    # 배치 끝나 _batch_status에서 제거된 경우
                    # /api/history/{runId}로 최종 상태 조회 시도
                    r2 = session.get(f"{PROD_URL}/api/history/{run_id}", timeout=15)
                    if r2.status_code == 200:
                        j = r2.json()
                        s = j.get('summary', {})
                        log(f"BATCH_COMPLETED (history) total={s.get('total')} passed={s.get('passed')} failed={s.get('failed')} errors={s.get('error', 0)}")
                        break
                continue
            status = r.json()
        except Exception as e:
            log(f"[POLL #{poll_count}] 오류: {str(e)[:200]}")
            continue

        completed = status.get('completed', 0)
        total = status.get('total', 0)
        if total_initial is None:
            total_initial = total
        passed = status.get('passed', 0)
        failed = status.get('failed', 0)
        errors = status.get('errors', 0)
        run_status = status.get('status', 'unknown')
        current = status.get('current', '')

        elapsed = time.time() - started_at
        pct = (completed / total * 100) if total > 0 else 0

        if completed != last_completed:
            delta = completed - last_completed if last_completed >= 0 else completed
            last_completed = completed
            last_progress_time = time.time()
            stall_warned = False
            eta_sec = ((elapsed / completed) * (total - completed)) if completed > 0 else 0
            eta_min = int(eta_sec / 60)
            log(f"PROGRESS {completed}/{total} ({pct:.1f}%) +{delta} "
                f"pass={passed} fail={failed} err={errors} "
                f"elapsed={int(elapsed/60)}m ETA={eta_min}m"
                + (f" current={current[:40]}" if current else ""))
        else:
            stall = time.time() - last_progress_time
            if stall > STALL_TIMEOUT and not stall_warned:
                log(f"STALL_WARN 진행 없음 {int(stall)}s @ {completed}/{total} (current={current[:40]})")
                stall_warned = True

        if time.time() - last_summary_time >= SUMMARY_EVERY:
            last_summary_time = time.time()
            log(f"SUMMARY [+{int(elapsed/60)}m] {completed}/{total} ({pct:.1f}%) "
                f"pass_rate={(passed/completed*100 if completed > 0 else 0):.1f}% "
                f"err_rate={(errors/completed*100 if completed > 0 else 0):.1f}%")

        if run_status == 'completed' or (total > 0 and completed >= total):
            log("=" * 70)
            log("BATCH_COMPLETED")
            log("=" * 70)
            log(f"총 시간: {int(elapsed/60)}분 {int(elapsed%60)}초")
            log(f"전체: {total}")
            log(f"통과: {passed} ({passed/total*100:.1f}%)")
            log(f"실패: {failed} ({failed/total*100:.1f}%)")
            log(f"오류: {errors} ({errors/total*100:.1f}%)")
            log(f"평균/시나리오: {elapsed/total:.2f}s")
            log(f"runId: {run_id}")

            out = Path(__file__).resolve().parent / f"batch_result_{run_id}.json"
            with open(out, 'w', encoding='utf-8') as f:
                json.dump({
                    'runId': run_id,
                    'total': total, 'passed': passed, 'failed': failed, 'errors': errors,
                    'elapsed_seconds': elapsed,
                    'completed_at': datetime.now(timezone.utc).isoformat(),
                }, f, ensure_ascii=False, indent=2)
            log(f"결과 저장: {out}")
            break

        if run_status == 'cancelled':
            log(f"BATCH_CANCELLED")
            break

    log("DONE")

if __name__ == '__main__':
    main()
