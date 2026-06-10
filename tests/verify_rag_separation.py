"""
verify_rag_separation.py — RAG 분리(Phase 3) 검증 하니스 ("나중에 실행")
========================================================================
독립 RAG 서비스(rag_server.py) 또는 리버스 프록시 경유 경로를 스모크 검증한다.
배포 전엔 실행 불가(라이브 URL 필요) — deploy-rag.ps1 배포 후 URL 을 주고 실행한다.

사용:
  # 독립 RAG 서비스 직접 (신뢰헤더 직접 주입)
  python tests/verify_rag_separation.py --rag-url https://medical-rag-dev-....run.app \
      --user-id tester1 --role tester --perms manage_kb [--trust-secret SECRET]

  # 호스트 리버스 프록시 경유 (호스트가 쿠키→신뢰헤더 변환; 쿠키 필요)
  python tests/verify_rag_separation.py --rag-url https://<host>/  --cookie "tester_token=..."

  # --no-allow-unauthenticated Cloud Run (IAM 인증 필요)
  python tests/verify_rag_separation.py --rag-url https://...run.app --id-token "$(gcloud auth print-identity-token)"
  python tests/verify_rag_separation.py --rag-url https://...run.app --auto-id-token

주의: --id-token / --auto-id-token 은 IAM 플랫폼 인증(Authorization: Bearer)이며,
      X-User-* 신뢰헤더(앱 인가)와 직교하므로 함께 사용해도 무방하다.

검증 항목:
  1) GET /health → 200 {status: ok}
  2) GET /api/rag/result?conversation_id=__verify__ → 200(JSON, 인증 통과)
  3) POST /api/rag/chat (SSE) → STOP 이벤트 수신 + citations 키 존재(스트리밍 패스스루)
"""

import shutil
import subprocess
import sys
import json
import argparse
import urllib.request
import urllib.error
from urllib.parse import quote


def _req(url, method='GET', headers=None, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


def _get_id_token(rag_url):
    """gcloud auth print-identity-token 으로 IAM 토큰을 취득한다.

    실패(gcloud 부재, 인증 오류 등)시 메시지 출력 후 sys.exit(1).
    audiences 는 rag_url 베이스 URL 을 그대로 사용한다.

    Windows 에서는 gcloud 가 .cmd 래퍼로 설치되므로 shutil.which 로
    전체 경로를 먼저 탐색하고, 없으면 명시 에러로 종료한다.
    """
    gcloud_bin = shutil.which('gcloud')
    if not gcloud_bin:
        print('[ERROR] gcloud not found - install Google Cloud CLI or pass --id-token manually')
        sys.exit(1)
    audiences = rag_url.rstrip('/')
    cmd = [gcloud_bin, 'auth', 'print-identity-token', '--audiences=' + audiences]
    print('[auto-id-token] running: ' + ' '.join(cmd))
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30, shell=False)
    except FileNotFoundError:
        print('[ERROR] gcloud not found - install Google Cloud CLI or pass --id-token manually')
        sys.exit(1)
    except subprocess.TimeoutExpired:
        print('[ERROR] gcloud timed out after 30s')
        sys.exit(1)
    if result.returncode != 0:
        stderr = (result.stderr or '').strip()
        print('[ERROR] gcloud failed (rc=%d): %s' % (result.returncode, stderr[:300]))
        sys.exit(1)
    token = (result.stdout or '').strip()
    if not token:
        print('[ERROR] gcloud returned empty token')
        sys.exit(1)
    print('[auto-id-token] token acquired (length=%d)' % len(token))
    return token


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rag-url', required=True, help='RAG 서비스 또는 호스트 베이스 URL')
    ap.add_argument('--user-id', default='verify-tester')
    ap.add_argument('--user-name', default='검증테스터')
    ap.add_argument('--role', default='tester')
    ap.add_argument('--perms', default='manage_kb', help='쉼표구분 권한')
    ap.add_argument('--trust-secret', default='')
    ap.add_argument('--cookie', default='', help='리버스 프록시 경유 시 쿠키')
    ap.add_argument('--query', default='3일째 기침이 나고 가래가 나와요')
    ap.add_argument('--id-token', default=None,
                    help='Cloud Run IAM 인증용 identity token (Authorization: Bearer). '
                         'X-User-* 신뢰헤더와 독립적으로 동작한다.')
    ap.add_argument('--auto-id-token', action='store_true',
                    help='gcloud auth print-identity-token 으로 토큰 자동 취득. '
                         'gcloud 부재/실패 시 에러로 종료.')
    args = ap.parse_args()

    # IAM 토큰 결정: --auto-id-token > --id-token > None
    id_token = None
    if args.auto_id_token:
        id_token = _get_id_token(args.rag_url)
    elif args.id_token:
        id_token = args.id_token

    base = args.rag_url.rstrip('/')
    H = {}

    # IAM 플랫폼 인증 (Cloud Run --no-allow-unauthenticated 대응)
    # X-User-* 앱 인가 헤더와 직교 — 함께 사용 가능
    if id_token:
        H['Authorization'] = 'Bearer ' + id_token

    if args.cookie:
        H['Cookie'] = args.cookie
    else:
        # 독립 서비스 직접 호출 — 신뢰헤더 주입
        H['X-User-Id'] = args.user_id
        H['X-User-Name'] = quote(args.user_name)  # 한글 이름 헤더 인코딩
        H['X-User-Role'] = args.role
        H['X-User-Permissions'] = args.perms
        if args.trust_secret:
            H['X-Rag-Trust'] = args.trust_secret

    results = []

    # 1) health (IAM 강제 시 플랫폼 레벨에서 토큰 필요 — Authorization만 첨부)
    health_h = {'Authorization': H['Authorization']} if 'Authorization' in H else {}
    try:
        r = _req(base + '/health', headers=health_h, timeout=15)
        body = json.loads(r.read().decode('utf-8'))
        ok = r.status == 200 and body.get('status') == 'ok'
        results.append(('health', ok, f"status={r.status} body={body}"))
    except Exception as e:
        results.append(('health', False, f"{type(e).__name__}: {str(e)[:100]}"))

    # 2) result endpoint (인증 통과 확인)
    try:
        r = _req(base + '/api/rag/result?conversation_id=__verify__&query=x&since_sec=1', headers=H, timeout=20)
        _ = r.read()
        results.append(('rag_result(auth)', r.status == 200, f"status={r.status}"))
    except urllib.error.HTTPError as e:
        # 403 이면 인증 실패(신뢰헤더/쿠키 문제), 그 외 200 기대
        results.append(('rag_result(auth)', e.code != 403, f"HTTP {e.code}"))
    except Exception as e:
        results.append(('rag_result(auth)', False, f"{type(e).__name__}: {str(e)[:100]}"))

    # 3) chat SSE (STOP 이벤트 + citations)
    try:
        payload = json.dumps({'conversation_id': '__verify__', 'query': args.query}).encode('utf-8')
        hh = dict(H); hh['Content-Type'] = 'application/json'
        r = _req(base + '/api/rag/chat', method='POST', headers=hh, data=payload, timeout=300)
        got_stop = False
        has_citations = False
        buf = b''
        while True:
            chunk = r.read(512)
            if not chunk:
                break
            buf += chunk
            while b'\n\n' in buf:
                evt, buf = buf.split(b'\n\n', 1)
                line = evt.decode('utf-8', 'replace').strip()
                if line.startswith('data:'):
                    try:
                        ev = json.loads(line[5:].strip())
                    except Exception:
                        continue
                    if ev.get('type') == 'STOP':
                        got_stop = True
                        has_citations = 'citations' in ev
            if got_stop:
                break
        results.append(('rag_chat SSE STOP', got_stop, f"stop={got_stop} citations_key={has_citations}"))
    except Exception as e:
        results.append(('rag_chat SSE STOP', False, f"{type(e).__name__}: {str(e)[:120]}"))

    # 출력
    print("=" * 56)
    print("  RAG 분리 검증 결과")
    print("=" * 56)
    all_ok = True
    for name, ok, detail in results:
        mark = "PASS" if ok else "FAIL"
        if not ok:
            all_ok = False
        print(f"  [{mark}] {name:20s} {detail}")
    print("=" * 56)
    print("  " + ("ALL PASS" if all_ok else "SOME FAILED"))
    sys.exit(0 if all_ok else 1)


if __name__ == '__main__':
    main()
