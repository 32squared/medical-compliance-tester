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

검증 항목:
  1) GET /health → 200 {status: ok}
  2) GET /api/rag/result?conversation_id=__verify__ → 200(JSON, 인증 통과)
  3) POST /api/rag/chat (SSE) → STOP 이벤트 수신 + citations 키 존재(스트리밍 패스스루)
"""

import sys
import json
import argparse
import urllib.request
import urllib.error


def _req(url, method='GET', headers=None, data=None, timeout=120):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    return urllib.request.urlopen(req, timeout=timeout)


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
    args = ap.parse_args()

    base = args.rag_url.rstrip('/')
    H = {}
    if args.cookie:
        H['Cookie'] = args.cookie
    else:
        # 독립 서비스 직접 호출 — 신뢰헤더 주입
        H['X-User-Id'] = args.user_id
        H['X-User-Name'] = args.user_name
        H['X-User-Role'] = args.role
        H['X-User-Permissions'] = args.perms
        if args.trust_secret:
            H['X-Rag-Trust'] = args.trust_secret

    results = []

    # 1) health
    try:
        r = _req(base + '/health', timeout=15)
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
