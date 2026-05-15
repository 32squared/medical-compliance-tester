"""이미 시작된 N개 shard 모니터링 (history 직접 폴링).
사용: monitor_shards.py runId1 runId2 ...
"""
import io, os, sys, time
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)

import requests

PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'
POLL = 30
SUMMARY_EVERY = 180
STALL_TIMEOUT = 1200


def log(m):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    rids = sys.argv[1:]
    if not rids:
        log("usage: monitor_shards.py runId1 ...")
        sys.exit(1)
    s = requests.Session()
    s.post(f"{PROD_URL}/api/auth/login",
           json={'id': 'admin', 'password': os.environ.get('ADMIN_PW', '')}, timeout=15)
    log(f"shards: {len(rids)}")

    states = {rid: {'done': False, 'total': 0, 'completed': 0, 'pass': 0, 'fail': 0} for rid in rids}
    started = time.time()
    last_total = -1
    last_prog_time = time.time()
    last_summary = time.time()

    while True:
        time.sleep(POLL)
        all_done = True
        agg_pass = agg_fail = total_completed = total_target = active = 0

        for rid in rids:
            if states[rid]['done']:
                total_completed += states[rid]['completed']
                total_target += states[rid]['total']
                agg_pass += states[rid]['pass']
                agg_fail += states[rid]['fail']
                continue
            try:
                r = s.get(f"{PROD_URL}/api/history/{rid}", timeout=15)
                if r.status_code != 200:
                    all_done = False
                    log(f"  {rid[-12:]}: HTTP {r.status_code}")
                    continue
                j = r.json()
                ss = j.get('summary') or {}
                total = ss.get('total', 0)
                p = ss.get('passed') or 0
                f = ss.get('failed') or 0
                proc = p + f
                run_status = j.get('status', '?')

                states[rid]['total'] = total
                states[rid]['completed'] = proc
                states[rid]['pass'] = p
                states[rid]['fail'] = f
                total_completed += proc
                total_target += total
                agg_pass += p
                agg_fail += f

                if run_status in ('completed', 'cancelled') or (total > 0 and proc >= total):
                    if not states[rid]['done']:
                        states[rid]['done'] = True
                        log(f"  shard {rid[-12:]} ended: pass={p} fail={f} status={run_status}")
                else:
                    all_done = False
                    active += 1
            except Exception as e:
                all_done = False
                log(f"  {rid[-12:]} err: {str(e)[:100]}")

        elapsed = time.time() - started
        pct = (total_completed / total_target * 100) if total_target > 0 else 0

        if total_completed != last_total:
            last_total = total_completed
            last_prog_time = time.time()
            eta = int(((elapsed / total_completed) * (total_target - total_completed)) / 60) if total_completed > 0 else 0
            log(f"PROGRESS {total_completed}/{total_target} ({pct:.1f}%) pass={agg_pass} fail={agg_fail} elapsed={int(elapsed/60)}m ETA={eta}m active={active}")
        else:
            stall = time.time() - last_prog_time
            if stall > STALL_TIMEOUT:
                log(f"STALL_WARN {int(stall/60)}m active={active}")
                if active == 0:
                    log("active=0 → 종료")
                    all_done = True

        if time.time() - last_summary >= SUMMARY_EVERY:
            last_summary = time.time()
            log(f"SUMMARY [+{int(elapsed/60)}m] {total_completed}/{total_target} ({pct:.1f}%) pass_rate={(agg_pass/total_completed*100 if total_completed > 0 else 0):.1f}% active={active}")

        if all_done:
            log("=" * 70)
            log(f"전체 완료 — {int(elapsed/60)}분")
            log(f"  처리: {total_completed}/{total_target}")
            log(f"  PASS: {agg_pass} ({agg_pass/total_completed*100:.1f}%)")
            log(f"  FAIL: {agg_fail}")
            for rid in rids:
                st = states[rid]
                log(f"    {rid}: {st['completed']}/{st['total']} (pass={st['pass']} fail={st['fail']})")
            break

    log("DONE")


if __name__ == '__main__':
    main()
