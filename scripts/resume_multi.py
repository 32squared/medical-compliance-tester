"""여러 이전 배치를 합쳐 미실행 시나리오만 새 배치로 보냄.
사용: resume_multi.py runId1 runId2 ...
"""
import io
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import requests

PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'
POLL_INTERVAL = 30
STALL_TIMEOUT = 900
SUMMARY_EVERY = 300


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def main():
    if len(sys.argv) < 2:
        log("usage: resume_multi.py runId1 [runId2 ...]")
        sys.exit(1)
    prev_runs = sys.argv[1:]
    admin_pw = os.environ.get('ADMIN_PW', '')
    if not admin_pw:
        log("[ERROR] ADMIN_PW")
        sys.exit(1)

    s = requests.Session()
    s.post(f"{PROD_URL}/api/auth/login",
           json={'id': 'admin', 'password': admin_pw}, timeout=15)

    # 모든 prev_run의 처리된 ID 수집
    processed = set()
    for prev in prev_runs:
        log(f"prev: {prev}")
        r = s.get(f"{PROD_URL}/api/history/{prev}", timeout=60)
        if r.status_code != 200:
            log(f"  HTTP {r.status_code} skip")
            continue
        j = r.json()
        results = j.get('results', [])
        ok = 0
        for rr in results:
            if rr.get('status') in ('pass', 'fail') and rr.get('scenarioId'):
                processed.add(rr['scenarioId'])
                ok += 1
        log(f"  처리됨(pass/fail): {ok}")
    log(f"총 처리된 unique: {len(processed)}")

    # 전체 시나리오에서 미처리만
    r = s.get(f"{PROD_URL}/api/scenarios", timeout=30)
    all_sc = r.json().get('scenarios', [])
    all_ids = [sc['id'] for sc in all_sc if sc.get('id')]
    remaining = [sid for sid in all_ids if sid not in processed]
    log(f"전체 {len(all_ids)} / 미실행 {len(remaining)}")

    if not remaining:
        log("미실행 없음 — 종료")
        return

    # 새 배치
    log(f"새 배치 시작 ({len(remaining)}건)...")
    started_at = time.time()
    r = s.post(f"{PROD_URL}/api/test/batch",
               json={'scenarioIds': remaining}, timeout=30)
    if r.status_code not in (200, 202):
        log(f"[ERROR] 배치 시작 실패 HTTP {r.status_code}: {r.text[:500]}")
        sys.exit(1)
    data = r.json()
    run_id = data.get('runId', '')
    log(f"new runId: {run_id}")
    log("=" * 70)

    last_completed = -1
    last_progress_time = time.time()
    last_summary_time = time.time()
    stall_warned = False

    while True:
        time.sleep(POLL_INTERVAL)
        try:
            r = s.get(f"{PROD_URL}/api/test/status/{run_id}", timeout=15)
            if r.status_code == 404:
                r2 = s.get(f"{PROD_URL}/api/history/{run_id}", timeout=15)
                if r2.status_code == 200:
                    jj = r2.json()
                    ss = jj.get('summary', {})
                    log(f"BATCH_ENDED (history) total={ss.get('total')} pass={ss.get('passed')} fail={ss.get('failed')} err={ss.get('error', 0)} status={jj.get('status', '?')}")
                    break
            if r.status_code != 200:
                log(f"  HTTP {r.status_code}")
                continue
            status = r.json()
        except Exception as e:
            log(f"  poll err: {str(e)[:200]}")
            continue

        completed = status.get('completed', 0)
        total = status.get('total', len(remaining))
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
            log(f"PROGRESS {completed}/{total} ({pct:.1f}%) +{delta} pass={passed} fail={failed} err={errors} elapsed={int(elapsed/60)}m ETA={eta_min}m" + (f" current={current[:30]}" if current else ""))
        else:
            stall = time.time() - last_progress_time
            if stall > STALL_TIMEOUT and not stall_warned:
                log(f"STALL_WARN {int(stall/60)}m @ {completed}/{total}")
                stall_warned = True

        if time.time() - last_summary_time >= SUMMARY_EVERY:
            last_summary_time = time.time()
            log(f"SUMMARY [+{int(elapsed/60)}m] {completed}/{total} ({pct:.1f}%) pass_rate={(passed/completed*100 if completed > 0 else 0):.1f}% err={errors}")

        if run_status in ('completed', 'cancelled') or (total > 0 and completed >= total):
            log("=" * 70)
            log(f"BATCH_ENDED status={run_status}")
            log(f"총 시간: {int(elapsed/60)}분")
            log(f"전체 {total} pass={passed} fail={failed} err={errors}")
            log(f"new runId: {run_id}")
            break

    log("DONE")


if __name__ == '__main__':
    main()
