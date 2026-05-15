"""기존 배치에서 미실행된 시나리오만 새 배치로 재실행 + 모니터링."""
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
STALL_TIMEOUT = 900    # 15분 (worst case 마지노선)
SUMMARY_EVERY = 300

def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)

def main():
    prev_run = sys.argv[1] if len(sys.argv) > 1 else 'batch-20260514-175526-0ae23b'
    admin_pw = os.environ.get('ADMIN_PW', '')
    if not admin_pw:
        log("[ERROR] ADMIN_PW 필요")
        sys.exit(1)

    s = requests.Session()
    log(f"prev_run = {prev_run}")
    log("admin 로그인...")
    r = s.post(f"{PROD_URL}/api/auth/login",
               json={'id': 'admin', 'password': admin_pw}, timeout=15)
    r.raise_for_status()

    # 1) 이전 배치에서 처리된 시나리오 ID 수집
    log("이전 배치 결과 조회...")
    r = s.get(f"{PROD_URL}/api/history/{prev_run}", timeout=60)
    r.raise_for_status()
    j = r.json()
    prev_results = j.get('results', [])
    # 실제 처리됨 (pass/fail)만 — error/누락은 재실행
    processed_ids = set(rr.get('scenarioId') for rr in prev_results
                         if rr.get('status') in ('pass', 'fail') and rr.get('scenarioId'))
    log(f"이미 처리됨: {len(processed_ids)}건")

    # 2) 전체 시나리오 조회 → 미실행만 추출
    log("전체 시나리오 조회...")
    r = s.get(f"{PROD_URL}/api/scenarios", timeout=30)
    r.raise_for_status()
    all_scenarios = r.json().get('scenarios', [])
    all_ids = [sc['id'] for sc in all_scenarios if sc.get('id')]
    remaining_ids = [sid for sid in all_ids if sid not in processed_ids]
    log(f"전체 시나리오: {len(all_ids)}, 미실행: {len(remaining_ids)}")

    if not remaining_ids:
        log("미실행 없음 — 종료")
        return

    # 3) 미실행 분만 새 배치
    log(f"새 배치 시작 ({len(remaining_ids)}건)...")
    started_at = time.time()
    r = s.post(f"{PROD_URL}/api/test/batch",
               json={'scenarioIds': remaining_ids}, timeout=30)
    if r.status_code not in (200, 202):
        log(f"[ERROR] 배치 시작 실패 HTTP {r.status_code}: {r.text[:500]}")
        sys.exit(1)
    data = r.json()
    run_id = data.get('runId', '')
    log(f"new runId: {run_id}")
    log("=" * 70)

    # 4) 모니터링
    last_completed = -1
    last_progress_time = time.time()
    last_summary_time = time.time()
    stall_warned = False

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            r = s.get(f"{PROD_URL}/api/test/status/{run_id}", timeout=15)
            if r.status_code != 200:
                if r.status_code == 404:
                    # 종료됨 → history 조회
                    r2 = s.get(f"{PROD_URL}/api/history/{run_id}", timeout=15)
                    if r2.status_code == 200:
                        jj = r2.json()
                        ss = jj.get('summary', {})
                        log(f"BATCH_ENDED (history) total={ss.get('total')} pass={ss.get('passed')} fail={ss.get('failed')} err={ss.get('error', 0)} status={jj.get('status', '?')}")
                        break
                log(f"  HTTP {r.status_code}")
                continue
            status = r.json()
        except Exception as e:
            log(f"  poll err: {str(e)[:200]}")
            continue

        completed = status.get('completed', 0)
        total = status.get('total', len(remaining_ids))
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
            eta_min = int(((elapsed / completed) * (total - completed)) / 60) if completed > 0 else 0
            log(f"PROGRESS {completed}/{total} ({pct:.1f}%) +{delta} "
                f"pass={passed} fail={failed} err={errors} "
                f"elapsed={int(elapsed/60)}m ETA={eta_min}m"
                + (f" current={current[:30]}" if current else ""))
        else:
            stall = time.time() - last_progress_time
            if stall > STALL_TIMEOUT and not stall_warned:
                log(f"STALL_WARN {int(stall/60)}m @ {completed}/{total}")
                stall_warned = True

        if time.time() - last_summary_time >= SUMMARY_EVERY:
            last_summary_time = time.time()
            log(f"SUMMARY [+{int(elapsed/60)}m] {completed}/{total} ({pct:.1f}%) "
                f"pass_rate={(passed/completed*100 if completed > 0 else 0):.1f}% "
                f"err={errors}")

        if run_status in ('completed', 'cancelled') or (total > 0 and completed >= total):
            log("=" * 70)
            log(f"BATCH_ENDED status={run_status}")
            log(f"총 시간: {int(elapsed/60)}분")
            log(f"전체 {total} pass={passed} fail={failed} err={errors}")
            log(f"new runId: {run_id}")
            log(f"prev runId: {prev_run}")
            log("→ 두 runId 결과를 합쳐 1100개 전체 분석 가능")
            break

    log("DONE")

if __name__ == '__main__':
    main()
