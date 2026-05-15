"""1100건을 N개 배치로 분할해 동시 실행 + 통합 모니터링.

기존 시도들의 누락분 합산 후 미실행만 N분할 → 동시 호출.
"""
import io
import json
import os
import sys
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import requests

PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'
SHARDS = 4
POLL_INTERVAL = 30
STALL_TIMEOUT = 900
SUMMARY_EVERY = 300


def log(msg):
    ts = datetime.now().strftime('%H:%M:%S')
    print(f"[{ts}] {msg}", flush=True)


def main():
    admin_pw = os.environ.get('ADMIN_PW', '')
    prev_runs = sys.argv[1:]  # 이전 배치들 (누락 추출용)

    s = requests.Session()
    r = s.post(f"{PROD_URL}/api/auth/login",
               json={'id': 'admin', 'password': admin_pw}, timeout=15)
    r.raise_for_status()
    log("admin 로그인 OK")

    # 이전 배치들의 처리된 ID 합산
    processed = set()
    for prev in prev_runs:
        try:
            r = s.get(f"{PROD_URL}/api/history/{prev}", timeout=60)
            if r.status_code != 200:
                continue
            j = r.json()
            for rr in j.get('results', []):
                if rr.get('status') in ('pass', 'fail') and rr.get('scenarioId'):
                    processed.add(rr['scenarioId'])
        except Exception as e:
            log(f"  prev {prev} skip: {e}")
    log(f"이전 처리됨: {len(processed)}건")

    # 전체 시나리오 → 미실행
    r = s.get(f"{PROD_URL}/api/scenarios", timeout=30)
    all_sc = r.json().get('scenarios', [])
    all_ids = [sc['id'] for sc in all_sc if sc.get('id')]
    remaining = [sid for sid in all_ids if sid not in processed]
    log(f"전체 {len(all_ids)} / 미실행 {len(remaining)}")

    if not remaining:
        log("미실행 없음")
        return

    # N 분할
    shard_size = (len(remaining) + SHARDS - 1) // SHARDS
    shards = [remaining[i:i+shard_size] for i in range(0, len(remaining), shard_size)]
    log(f"{SHARDS}분할 — 각 ~{shard_size}건")

    # 동시 시작
    started_at = time.time()
    run_ids = []
    for i, shard in enumerate(shards, start=1):
        try:
            r = s.post(f"{PROD_URL}/api/test/batch",
                       json={'scenarioIds': shard}, timeout=30)
            if r.status_code not in (200, 202):
                log(f"  shard {i} 시작 실패: HTTP {r.status_code} {r.text[:200]}")
                continue
            d = r.json()
            run_ids.append((i, d.get('runId', ''), len(shard)))
            log(f"  shard {i} 시작: runId={d.get('runId')} ({len(shard)}건)")
        except Exception as e:
            log(f"  shard {i} 예외: {e}")

    if not run_ids:
        log("[ERROR] 배치 시작 실패")
        return

    log("=" * 70)
    log(f"동시 {len(run_ids)}개 배치 모니터링 시작")
    log("=" * 70)

    # 통합 모니터링
    last_progress_time = time.time()
    last_summary_time = time.time()
    states = {rid: {'completed': -1, 'total': cnt, 'done': False}
              for _, rid, cnt in run_ids}

    while True:
        time.sleep(POLL_INTERVAL)
        all_done = True
        total_completed = 0
        total_target = 0
        agg_pass = 0
        agg_fail = 0
        agg_err = 0
        active_count = 0

        for shard_no, rid, cnt in run_ids:
            if states[rid]['done']:
                total_completed += states[rid].get('finalCompleted', cnt)
                total_target += cnt
                continue

            # 모든 shard는 history 직접 조회 (concurrency=1 분산 환경)
            # status endpoint는 호출된 인스턴스의 메모리만 보므로 404 흔함
            try:
                r2 = s.get(f"{PROD_URL}/api/history/{rid}", timeout=15)
                if r2.status_code == 200:
                    jj = r2.json()
                    ss = jj.get('summary', {})
                    proc = (ss.get('passed') or 0) + (ss.get('failed') or 0)
                    run_status = jj.get('status', '?')
                    p = ss.get('passed') or 0
                    f = ss.get('failed') or 0
                    e_ = ss.get('error') or 0
                    states[rid]['completed'] = proc
                    states[rid]['status'] = run_status
                    total_completed += proc
                    total_target += cnt
                    agg_pass += p
                    agg_fail += f
                    # error는 미실행을 포함하므로 신뢰 안 함

                    if run_status in ('completed', 'cancelled') or proc >= cnt:
                        states[rid]['done'] = True
                        states[rid]['finalCompleted'] = proc
                        log(f"  shard {shard_no} ({rid}) ended: pass={p} fail={f} status={run_status} (proc={proc}/{cnt})")
                    else:
                        # 아직 실행 중 (running)
                        all_done = False
                        active_count += 1
                else:
                    all_done = False
                    log(f"  shard {shard_no} history HTTP {r2.status_code}")
            except Exception as e:
                all_done = False
                log(f"  shard {shard_no} poll err: {str(e)[:120]}")

        # 통합 진행
        elapsed = time.time() - started_at
        pct = (total_completed / total_target * 100) if total_target > 0 else 0
        eta_min = int(((elapsed / total_completed) * (total_target - total_completed)) / 60) if total_completed > 0 else 0

        # 진행 갱신
        if total_completed != getattr(main, '_last_total', -1):
            main._last_total = total_completed
            last_progress_time = time.time()
            log(f"PROGRESS total={total_completed}/{total_target} ({pct:.1f}%) pass={agg_pass} fail={agg_fail} err={agg_err} elapsed={int(elapsed/60)}m ETA={eta_min}m active={active_count}")
        else:
            stall = time.time() - last_progress_time
            if stall > STALL_TIMEOUT:
                log(f"STALL_WARN {int(stall/60)}m no progress")
                # active=0이면 모두 cancelled — 종료
                if active_count == 0:
                    log("모든 shard 종료됨 (active=0). 자동 종료.")
                    all_done = True

        if time.time() - last_summary_time >= SUMMARY_EVERY:
            last_summary_time = time.time()
            log(f"SUMMARY [+{int(elapsed/60)}m] {total_completed}/{total_target} ({pct:.1f}%) pass_rate={(agg_pass/total_completed*100 if total_completed > 0 else 0):.1f}% active_shards={active_count}")

        if all_done:
            log("=" * 70)
            log(f"전체 완료 — 총 {int(elapsed/60)}분")
            log(f"  처리: {total_completed}/{total_target}")
            log(f"  shard runIds:")
            for shard_no, rid, _ in run_ids:
                log(f"    {shard_no}: {rid}")
            break

    log("DONE")


if __name__ == '__main__':
    main()
