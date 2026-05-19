"""PROD API 직접 호출 진단.

임시 admin session 생성 → /api/healthbench/scenario/_/HB-XXXX API 호출 → 응답
raw JSON 출력. 사용 후 session 삭제.

실행:
  VERIFY_SCENARIO_ID=HB-XXXX python scripts/diagnose_api_response.py
"""
import json
import os
import secrets
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db

PUBLIC_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'


def main():
    sid = os.environ.get('VERIFY_SCENARIO_ID', '').strip()
    if not sid:
        raise SystemExit('VERIFY_SCENARIO_ID env var 필요')

    print(f'=== API 직접 호출 진단: {sid} ===', flush=True)

    # 1. 임시 admin session 생성
    token = secrets.token_urlsafe(32)
    db.save_session(token, 'admin', user_name='diagnose-tool', max_age=300)
    print(f'admin session 생성됨 (5분 만료)', flush=True)

    try:
        # 2. 두 가지 케이스 호출
        # (a) run_id='_' (없음)
        # (b) 실제 존재하는 run_id (job-20260518-191745-3b1b90)
        for label, run_id in [('run_id=_', '_'), ('run_id=job-20260518-191745-3b1b90', 'job-20260518-191745-3b1b90')]:
            print(f'\n--- 호출: {label} ---', flush=True)
            url = f'{PUBLIC_URL}/api/healthbench/scenario/{run_id}/{sid}'
            print(f'URL: {url}', flush=True)
            req = urllib.request.Request(url, headers={
                'Cookie': f'admin_token={token}',
                'Accept': 'application/json',
            })
            try:
                resp = urllib.request.urlopen(req, timeout=20)
                body = resp.read().decode('utf-8')
                data = json.loads(body)
                print(f'HTTP {resp.status}', flush=True)
                print(f'  scenarioMissing: {data.get("scenarioMissing")}', flush=True)
                print(f'  resultFromFallback: {data.get("resultFromFallback")}', flush=True)
                print(f'  requestedRunId: {data.get("requestedRunId")}', flush=True)
                # scenario
                s = data.get('scenario')
                if s:
                    print(f'  scenario: id={s.get("id")}, subcategory={s.get("subcategory")}, turns={len(s.get("turns") or [])}, rubric={len(s.get("rubric") or [])}', flush=True)
                else:
                    print(f'  scenario: null', flush=True)
                # run
                r = data.get('run')
                if r:
                    print(f'  run: runId={r.get("runId")}, status={r.get("status")}, startedAt={r.get("startedAt")}', flush=True)
                else:
                    print(f'  run: null', flush=True)
                # result
                res = data.get('result')
                if res:
                    print(f'  result: status={res.get("status")}, finalScore={res.get("finalScore")}, turnResults={len(res.get("turnResults") or [])}', flush=True)
                    re = res.get('rubricEval') or {}
                    print(f'    rubricEval: score={re.get("score")} met={re.get("metCount")}/{re.get("totalCount")} items={len(re.get("items") or [])}', flush=True)
                else:
                    print(f'  result: null', flush=True)
                # raw body 일부
                print(f'  raw response (앞 400자): {body[:400]}', flush=True)
            except urllib.error.HTTPError as e:
                print(f'HTTP {e.code} ERROR: {e.read().decode("utf-8")[:200]}', flush=True)
            except Exception as e:
                print(f'EXCEPTION: {type(e).__name__}: {str(e)[:200]}', flush=True)
    finally:
        # cleanup
        with db.get_conn() as (conn, cur):
            ph = db._p()
            cur.execute(f'DELETE FROM sessions WHERE token = {ph}', (token,))
        print('\nadmin session 삭제 완료', flush=True)


if __name__ == '__main__':
    main()
