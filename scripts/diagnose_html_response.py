"""embed 페이지 HTML 응답 + iframe 내부 fetch 시뮬레이션."""
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
    sid = os.environ.get('VERIFY_SCENARIO_ID', 'HB-C0D1DD5E').strip()
    token = secrets.token_urlsafe(32)
    db.save_session(token, 'admin', user_name='diagnose-tool', max_age=300)
    print(f'=== embed HTML 응답 진단: {sid} ===', flush=True)

    try:
        url = f'{PUBLIC_URL}/healthbench/scenario?id={sid}&embed=1'
        print(f'URL: {url}', flush=True)
        req = urllib.request.Request(url, headers={'Cookie': f'admin_token={token}'})
        resp = urllib.request.urlopen(req, timeout=20)
        body = resp.read().decode('utf-8')
        print(f'HTTP {resp.status}, size={len(body)} chars', flush=True)
        # iframe 페이지가 응답하는 HTML 의 핵심 요소 확인
        for marker in [
            'mainContent',
            'detailModalSid',
            'function load()',
            'function render(',
            'getParams()',
            'fetch(url)',
            "ok = await checkAuth",
            'body.classList.add',
        ]:
            present = marker in body
            print(f'  [{"OK " if present else "MISS"}] "{marker}"', flush=True)
        print('', flush=True)
        # 추가로 같은 cookie 로 API 호출도 확인 (iframe 안에서 호출됐을 때 cookie 전달되는지)
        api = f'{PUBLIC_URL}/api/healthbench/scenario/_/{sid}'
        req2 = urllib.request.Request(api, headers={'Cookie': f'admin_token={token}'})
        r2 = urllib.request.urlopen(req2, timeout=20)
        b2 = r2.read().decode('utf-8')
        d = json.loads(b2)
        print(f'API 직접 호출 응답: status={r2.status}', flush=True)
        print(f'  scenario 있음? {d.get("scenario") is not None}', flush=True)
        print(f'  result 있음? {d.get("result") is not None}', flush=True)
        print(f'  resultFromFallback: {d.get("resultFromFallback")}', flush=True)
    finally:
        with db.get_conn() as (conn, cur):
            ph = db._p()
            cur.execute(f'DELETE FROM sessions WHERE token = {ph}', (token,))


if __name__ == '__main__':
    main()
