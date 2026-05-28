"""
RAG KB API 통합 테스트 — 로컬 서버 대상 (subprocess로 서버 기동)

실행 방법:
  python tests/test_rag_kb_api.py              # 기본: localhost:9000
  python tests/test_rag_kb_api.py --url http://localhost:9001
  python tests/test_rag_kb_api.py --no-server  # 이미 실행 중인 서버 사용
  pytest tests/test_rag_kb_api.py -v           # pytest 실행

테스트 케이스:
  1. 미인증 요청 → 401/403
  2. manage_kb 권한 없이 POST /documents → 403
  3. 정상 흐름: sources 조회 → 문서 생성 → 단건 조회 → 승인 → 삭제
  4. DELETE 후 GET → 404
  5. reject reason 누락 → 400
  6. /api/auth/me 응답 구조 검증
"""

import sys
import os
import json
import time
import argparse
import subprocess
import urllib.request
import urllib.error
import urllib.parse
import socket
import threading

# 프로젝트 루트를 경로에 추가
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# ── 기본 설정 ──────────────────────────────────────────────────
DEFAULT_PORT = 19199   # 테스트 전용 포트 (기존 서버와 충돌 방지)
DEFAULT_URL = f'http://localhost:{DEFAULT_PORT}'

PASS_MARK = 'PASS'
FAIL_MARK = 'FAIL'
SKIP_MARK = 'SKIP'

_results = {'pass': 0, 'fail': 0, 'skip': 0}
_server_proc = None


# ── 헬퍼 ──────────────────────────────────────────────────────

def _req(method: str, path: str, body=None, headers: dict = None,
         admin_token: str = None, tester_token: str = None,
         base_url: str = DEFAULT_URL):
    """HTTP 요청 헬퍼. (status_code, response_dict) 반환."""
    url = base_url + path
    data = json.dumps(body).encode('utf-8') if body is not None else None
    h = {'Content-Type': 'application/json'}
    if headers:
        h.update(headers)
    cookie_parts = []
    if admin_token:
        cookie_parts.append(f'admin_token={admin_token}')
    if tester_token:
        cookie_parts.append(f'tester_token={tester_token}')
    if cookie_parts:
        h['Cookie'] = '; '.join(cookie_parts)

    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode('utf-8')
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read().decode('utf-8', errors='replace')
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {'error': raw[:300]}
    except Exception as e:
        return 0, {'error': str(e)}


def check(name: str, condition: bool, info: str = ''):
    if condition:
        print(f'  {PASS_MARK}  {name}')
        _results['pass'] += 1
    else:
        detail = f'  [{info}]' if info else ''
        print(f'  {FAIL_MARK}  {name}{detail}')
        _results['fail'] += 1


def skip(name: str, reason: str = ''):
    print(f'  {SKIP_MARK}  {name}' + (f' ({reason})' if reason else ''))
    _results['skip'] += 1


# ── 서버 기동/종료 ─────────────────────────────────────────────

def _is_port_open(port: int, host: str = 'localhost') -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def _start_server(port: int) -> subprocess.Popen:
    """proxy_server.py를 별도 프로세스로 기동."""
    import sys as _sys
    server_script = os.path.join(_REPO_ROOT, 'proxy_server.py')
    proc = subprocess.Popen(
        [_sys.executable, server_script, '--port', str(port)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=_REPO_ROOT,
    )
    # 최대 8초 대기
    for _ in range(40):
        if _is_port_open(port):
            return proc
        time.sleep(0.2)
    proc.terminate()
    raise RuntimeError(f'서버가 {port}번 포트에서 8초 내로 응답하지 않았습니다')


def _stop_server(proc: subprocess.Popen):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


# ── Admin 로그인 헬퍼 ────────────────────────────────────────

def _admin_login(base_url: str) -> str:
    """Admin 로그인 후 토큰 반환. setup이 안 된 경우 setup 먼저 수행."""
    # setup 상태 확인
    status_code, status_body = _req('GET', '/api/auth/status', base_url=base_url)
    is_setup = status_body.get('isSetup', False) if status_code == 200 else False

    if not is_setup:
        # 초기 setup
        sc, sb = _req('POST', '/api/auth/setup',
                      body={'password': 'test_admin_pw_!'},
                      base_url=base_url)
        if sc not in (200, 201):
            return ''

    # 로그인
    sc, sb = _req('POST', '/api/auth/login',
                  body={'password': 'test_admin_pw_!'},
                  base_url=base_url)
    if sc != 200:
        return ''

    # 쿠키 토큰 추출은 직접 불가 (urllib) → admin_token을 별도로 추출
    # 로그인 응답 본문만 사용하고, 실제 테스트는 쿠키 없이 진행하기 어려우므로
    # DB에서 직접 세션 토큰을 생성하는 방법 사용
    # → 여기서는 DB 직접 조작으로 토큰 생성
    try:
        sys.path.insert(0, _REPO_ROOT)
        import db as _db
        token = 'test_admin_token_' + str(int(time.time()))
        _db.save_session(token, 'admin', user_id='admin', user_name='관리자', max_age=3600)
        return token
    except Exception as e:
        print(f'  [경고] admin 토큰 생성 실패: {e}')
        return ''


def _create_test_tester(base_url: str, admin_token: str) -> str:
    """테스트용 tester 계정 생성 후 tester 세션 토큰 반환."""
    try:
        import db as _db
        import secrets as _secrets
        import hashlib as _hl

        user_id = 'test_tester_kb_' + str(int(time.time()))
        salt = _secrets.token_hex(16)
        pw_hash = _hl.pbkdf2_hmac(
            'sha256', b'tester_pw_!', salt.encode('utf-8'), 100000
        ).hex()

        with _db.get_conn() as (conn, cur):
            cur.execute(
                f"""INSERT INTO users (id, name, org, password_hash, password_salt,
                    status, role, uid, created_at, approved_at, permissions)
                    VALUES ({_db._ph(11)})""",
                (user_id, user_id, '', pw_hash, salt,
                 'approved', 'tester', '', _db._now(), _db._now(), '[]')
            )

        token = 'test_tester_token_' + _secrets.token_hex(8)
        _db.save_session(token, 'tester', user_id=user_id,
                         user_name=user_id, max_age=3600)
        return token, user_id
    except Exception as e:
        print(f'  [경고] tester 계정 생성 실패: {e}')
        return '', ''


def _ensure_test_kb_source(source_id: str = 'test_source_kb_api'):
    """테스트용 kb_sources 레코드가 없으면 INSERT."""
    try:
        import db as _db
        with _db.get_conn() as (conn, cur):
            cur.execute(
                f"SELECT id FROM kb_sources WHERE id = {_db._p()}",
                (source_id,)
            )
            if not cur.fetchone():
                cur.execute(
                    f"""INSERT INTO kb_sources
                        (id, name, source_type, license, url, is_active, created_at)
                        VALUES ({_db._ph(7)})""",
                    (source_id, '테스트 소스', 'manual', 'MIT',
                     None, 1, _db._now())
                )
        return source_id
    except Exception as e:
        print(f'  [경고] kb_sources 시드 실패: {e}')
        return source_id


# ════════════════════════════════════════════════════
# 테스트 케이스
# ════════════════════════════════════════════════════

def run_tests(base_url: str):
    print(f'\n[RAG KB API 테스트] 대상: {base_url}\n')

    admin_token = _admin_login(base_url)
    if not admin_token:
        print('  [오류] Admin 토큰을 얻지 못했습니다. 테스트를 건너뜁니다.')
        return

    tester_token, tester_user_id = _create_test_tester(base_url, admin_token)
    source_id = _ensure_test_kb_source()

    created_doc_id = None  # 생성된 문서 ID를 테스트 간 공유

    # ─────────────────────────────────────────
    print('[ 1. 미인증 요청 → 401/403 ]')
    # ─────────────────────────────────────────

    sc, body = _req('GET', '/api/rag/kb/sources', base_url=base_url)
    check('GET /api/rag/kb/sources (미인증) → 4xx',
          sc in (401, 403), f'sc={sc}')

    sc, body = _req('GET', '/api/rag/kb/documents', base_url=base_url)
    check('GET /api/rag/kb/documents (미인증) → 4xx',
          sc in (401, 403), f'sc={sc}')

    sc, body = _req('POST', '/api/rag/kb/documents',
                    body={'title': 'x', 'content_md': 'x', 'source_id': 'x'},
                    base_url=base_url)
    check('POST /api/rag/kb/documents (미인증) → 4xx',
          sc in (401, 403), f'sc={sc}')

    sc, body = _req('POST', '/api/rag/kb/approve',
                    body={'document_id': 'fake'},
                    base_url=base_url)
    check('POST /api/rag/kb/approve (미인증) → 4xx',
          sc in (401, 403), f'sc={sc}')

    sc, body = _req('POST', '/api/rag/kb/reject',
                    body={'document_id': 'fake', 'reason': 'x'},
                    base_url=base_url)
    check('POST /api/rag/kb/reject (미인증) → 4xx',
          sc in (401, 403), f'sc={sc}')

    sc, body = _req('DELETE', '/api/rag/kb/documents/fake_id',
                    base_url=base_url)
    check('DELETE /api/rag/kb/documents/{id} (미인증) → 4xx',
          sc in (401, 403), f'sc={sc}')

    # ─────────────────────────────────────────
    print('\n[ 2. manage_kb 권한 없는 tester → 403 ]')
    # ─────────────────────────────────────────

    if not tester_token:
        skip('tester 권한 없음 테스트', '토큰 생성 실패')
    else:
        sc, body = _req('POST', '/api/rag/kb/documents',
                        body={'title': '권한없음 테스트', 'content_md': '# 내용\n테스트',
                              'source_id': source_id},
                        tester_token=tester_token,
                        base_url=base_url)
        check('POST /documents (manage_kb 없는 tester) → 403',
              sc == 403, f'sc={sc}, body={body}')

        sc, body = _req('POST', '/api/rag/kb/approve',
                        body={'document_id': 'fake'},
                        tester_token=tester_token,
                        base_url=base_url)
        check('POST /approve (manage_kb 없는 tester) → 403',
              sc == 403, f'sc={sc}')

        sc, body = _req('POST', '/api/rag/kb/reject',
                        body={'document_id': 'fake', 'reason': 'x'},
                        tester_token=tester_token,
                        base_url=base_url)
        check('POST /reject (manage_kb 없는 tester) → 403',
              sc == 403, f'sc={sc}')

    # ─────────────────────────────────────────
    print('\n[ 3. GET sources / documents (admin 인증) ]')
    # ─────────────────────────────────────────

    sc, body = _req('GET', '/api/rag/kb/sources',
                    admin_token=admin_token, base_url=base_url)
    check('GET /api/rag/kb/sources (admin) → 200, list',
          sc == 200 and isinstance(body, list), f'sc={sc}')

    sc, body = _req('GET', '/api/rag/kb/documents',
                    admin_token=admin_token, base_url=base_url)
    check('GET /api/rag/kb/documents (admin) → 200, {documents, total}',
          sc == 200 and 'documents' in body and 'total' in body,
          f'sc={sc}, keys={list(body.keys()) if isinstance(body, dict) else body}')

    # ─────────────────────────────────────────
    print('\n[ 4. POST /documents → 문서 생성 ]')
    # ─────────────────────────────────────────

    sc, body = _req('POST', '/api/rag/kb/documents',
                    body={
                        'title': '[KB API 테스트] 발열 관리 가이드',
                        'content_md': (
                            '# 발열 관리 가이드\n\n'
                            '38도 이상의 발열은 감염 등의 원인이 될 수 있습니다.\n\n'
                            '## 자가 관리\n\n'
                            '충분한 수분 섭취와 휴식이 중요합니다.\n\n'
                            '## 병원 방문 기준\n\n'
                            '39.5도 이상 지속 또는 3일 이상 지속 시 내과 진료를 권장합니다.'
                        ),
                        'source_id': source_id,
                        'metadata': {'symptom_tags': ['발열', '열'], 'severity': 'low'},
                        'status': 'draft',
                    },
                    admin_token=admin_token,
                    base_url=base_url)
    check('POST /api/rag/kb/documents (admin) → 201, document_id',
          sc == 201 and 'document_id' in body,
          f'sc={sc}, body={body}')

    if sc == 201:
        created_doc_id = body['document_id']
        print(f'     생성된 doc_id: {created_doc_id}, chunks: {body.get("chunks_count")}')

    # ─────────────────────────────────────────
    print('\n[ 5. GET /documents/{id} (단건 조회) ]')
    # ─────────────────────────────────────────

    if not created_doc_id:
        skip('GET /documents/{id}', '문서 생성 실패로 건너뜀')
    else:
        sc, body = _req('GET', f'/api/rag/kb/documents/{created_doc_id}',
                        admin_token=admin_token, base_url=base_url)
        check('GET /documents/{id} → 200, chunks 포함',
              sc == 200 and 'chunks' in body and isinstance(body.get('chunks'), list),
              f'sc={sc}')
        check('GET /documents/{id} → title 일치',
              sc == 200 and '[KB API 테스트]' in body.get('title', ''),
              f'title={body.get("title", "")}')

    # ─────────────────────────────────────────
    print('\n[ 6. PUT /documents/{id} (메타 수정) ]')
    # ─────────────────────────────────────────

    if not created_doc_id:
        skip('PUT /documents/{id}', '문서 생성 실패로 건너뜀')
    else:
        sc, body = _req('PUT', f'/api/rag/kb/documents/{created_doc_id}',
                        body={'status': 'pending_review',
                              'evidence_level': 'A'},
                        admin_token=admin_token,
                        base_url=base_url)
        check('PUT /documents/{id} → 200, {updated: true}',
              sc == 200 and body.get('updated') is True,
              f'sc={sc}, body={body}')

    # ─────────────────────────────────────────
    print('\n[ 7. POST /approve → 문서 승인 ]')
    # ─────────────────────────────────────────

    if not created_doc_id:
        skip('POST /approve', '문서 생성 실패로 건너뜀')
    else:
        sc, body = _req('POST', '/api/rag/kb/approve',
                        body={'document_id': created_doc_id},
                        admin_token=admin_token,
                        base_url=base_url)
        check('POST /approve → 200, {approved: true}',
              sc == 200 and body.get('approved') is True,
              f'sc={sc}, body={body}')

        # 승인 후 status=active 확인
        sc2, body2 = _req('GET', f'/api/rag/kb/documents/{created_doc_id}',
                          admin_token=admin_token, base_url=base_url)
        check('승인 후 status=active 확인',
              sc2 == 200 and body2.get('status') == 'active',
              f'status={body2.get("status")}')

    # ─────────────────────────────────────────
    print('\n[ 8. POST /reject reason 누락 → 400 ]')
    # ─────────────────────────────────────────

    sc, body = _req('POST', '/api/rag/kb/reject',
                    body={'document_id': created_doc_id or 'fake'},
                    admin_token=admin_token,
                    base_url=base_url)
    check('POST /reject reason 누락 → 400',
          sc == 400, f'sc={sc}, error={body.get("error", "")}')

    # ─────────────────────────────────────────
    print('\n[ 9. reject 정상 (문서 생성 후) ]')
    # ─────────────────────────────────────────

    # 별도 draft 문서를 생성하여 reject
    sc_r, body_r = _req('POST', '/api/rag/kb/documents',
                        body={
                            'title': '[KB API 테스트] reject 대상 문서',
                            'content_md': '# 테스트\n반려될 문서입니다.',
                            'source_id': source_id,
                            'metadata': {},
                            'status': 'draft',
                        },
                        admin_token=admin_token,
                        base_url=base_url)
    reject_doc_id = body_r.get('document_id') if sc_r == 201 else None

    if reject_doc_id:
        sc, body = _req('POST', '/api/rag/kb/reject',
                        body={'document_id': reject_doc_id, 'reason': '내용 부정확'},
                        admin_token=admin_token,
                        base_url=base_url)
        check('POST /reject (reason 있음) → 200, {rejected: true}',
              sc == 200 and body.get('rejected') is True,
              f'sc={sc}, body={body}')
    else:
        skip('POST /reject 정상', '테스트용 문서 생성 실패')

    # ─────────────────────────────────────────
    print('\n[ 10. DELETE /documents/{id} → 404 ]')
    # ─────────────────────────────────────────

    if not created_doc_id:
        skip('DELETE /documents/{id} + 재조회', '문서 생성 실패로 건너뜀')
    else:
        sc, body = _req('DELETE', f'/api/rag/kb/documents/{created_doc_id}',
                        admin_token=admin_token, base_url=base_url)
        check('DELETE /documents/{id} → 200, {deleted: true}',
              sc == 200 and body.get('deleted') is True,
              f'sc={sc}, body={body}')

        # 삭제 후 재조회 → 404
        sc2, body2 = _req('GET', f'/api/rag/kb/documents/{created_doc_id}',
                          admin_token=admin_token, base_url=base_url)
        check('DELETE 후 GET → 404',
              sc2 == 404, f'sc={sc2}')

    # reject_doc_id 정리
    if reject_doc_id:
        _req('DELETE', f'/api/rag/kb/documents/{reject_doc_id}',
             admin_token=admin_token, base_url=base_url)

    # ─────────────────────────────────────────
    print('\n[ 11. GET /api/auth/me 응답 구조 ]')
    # ─────────────────────────────────────────

    sc, body = _req('GET', '/api/auth/me',
                    admin_token=admin_token, base_url=base_url)
    check('GET /api/auth/me (admin) → 200, role=admin',
          sc == 200 and body.get('role') == 'admin',
          f'sc={sc}, body={body}')
    check('GET /api/auth/me (admin) → permissions=["*"]',
          sc == 200 and body.get('permissions') == ['*'],
          f'permissions={body.get("permissions")}')

    sc, body = _req('GET', '/api/auth/me', base_url=base_url)
    check('GET /api/auth/me (미인증) → 401',
          sc == 401, f'sc={sc}')

    if tester_token:
        sc, body = _req('GET', '/api/auth/me',
                        tester_token=tester_token, base_url=base_url)
        check('GET /api/auth/me (tester) → 200, role, permissions',
              sc == 200 and 'role' in body and 'permissions' in body,
              f'sc={sc}, body={body}')

    # ─────────────────────────────────────────
    print('\n[ 12. 페이지네이션 / 필터 ]')
    # ─────────────────────────────────────────

    sc, body = _req('GET', '/api/rag/kb/documents?page=1&page_size=5',
                    admin_token=admin_token, base_url=base_url)
    check('GET /documents?page=1&page_size=5 → page_size 필드',
          sc == 200 and body.get('page_size') == 5,
          f'sc={sc}, page_size={body.get("page_size")}')

    sc, body = _req('GET', '/api/rag/kb/documents?status=active',
                    admin_token=admin_token, base_url=base_url)
    check('GET /documents?status=active → 200',
          sc == 200, f'sc={sc}')

    # ─────────────────────────────────────────
    print('\n[ 13. 존재하지 않는 문서 → 404 ]')
    # ─────────────────────────────────────────

    sc, body = _req('GET', '/api/rag/kb/documents/nonexistent_doc_id_12345',
                    admin_token=admin_token, base_url=base_url)
    check('GET 존재하지 않는 문서 → 404',
          sc == 404, f'sc={sc}')

    sc, body = _req('DELETE', '/api/rag/kb/documents/nonexistent_doc_id_12345',
                    admin_token=admin_token, base_url=base_url)
    check('DELETE 존재하지 않는 문서 → 404',
          sc == 404, f'sc={sc}')

    # ─────────────────────────────────────────
    # 결과 요약
    # ─────────────────────────────────────────
    total = _results['pass'] + _results['fail'] + _results['skip']
    print(f'\n{"=" * 55}')
    print(f'결과: {_results["pass"]} 통과 / {_results["fail"]} 실패 / {_results["skip"]} 건너뜀 (총 {total})')
    print('=' * 55)

    if _results['fail'] > 0:
        sys.exit(1)


# ════════════════════════════════════════════════════
# pytest 호환 (함수 단위 테스트)
# ════════════════════════════════════════════════════

# pytest가 있는 환경에서 개별 케이스를 실행할 수 있도록
# 최소한의 구조만 제공 (전체 통합 테스트는 run_tests()로)

def _grep_proxy(pattern: str) -> bool:
    """proxy_server.py 소스 코드에서 패턴 존재 여부 확인 (import 없이)."""
    import re as _re
    proxy_path = os.path.join(_REPO_ROOT, 'proxy_server.py')
    with open(proxy_path, 'r', encoding='utf-8') as f:
        src = f.read()
    return bool(_re.search(pattern, src))


def test_permission_catalog_has_manage_kb():
    """PERMISSION_CATALOG에 manage_kb가 등록되어 있는지 확인 (소스 코드 레벨)"""
    # proxy_server.py를 직접 import하면 sys.stdout 래핑으로 pytest capture 깨짐
    # → 소스 텍스트 grep으로 검증
    assert _grep_proxy(r"'code':\s*'manage_kb'"), \
        "manage_kb not found in PERMISSION_CATALOG"


def test_proxy_server_syntax():
    """proxy_server.py 문법 오류 없음 확인 (py_compile)"""
    import py_compile
    proxy_path = os.path.join(_REPO_ROOT, 'proxy_server.py')
    # doraise=True 이면 SyntaxError 발생
    py_compile.compile(proxy_path, doraise=True)


def test_rag_kb_handler_methods_exist():
    """proxy_server.py 소스에 RAG KB 핸들러 메서드들이 정의되어 있는지 확인"""
    methods = [
        '_rag_kb_list_sources',
        '_rag_kb_list_documents',
        '_rag_kb_get_document',
        '_rag_kb_create_document',
        '_rag_kb_update_document',
        '_rag_kb_delete_document',
        '_rag_kb_approve_document',
        '_rag_kb_reject_document',
        '_rag_kb_reembed_document',
        '_auth_me',
    ]
    missing = [m for m in methods if not _grep_proxy(rf'def {m}\b')]
    assert not missing, f'다음 메서드가 proxy_server.py에 없습니다: {missing}'


def test_kb_routes_in_do_get():
    """do_GET 라우팅에 /api/rag/kb/ 분기가 존재하는지 확인"""
    assert _grep_proxy(r'/api/rag/kb/sources'), \
        "/api/rag/kb/sources route not found in do_GET"
    assert _grep_proxy(r'/api/rag/kb/documents'), \
        "/api/rag/kb/documents route not found"


def test_kb_routes_in_do_post():
    """do_POST 라우팅에 /api/rag/kb/approve, /api/rag/kb/reject 분기 존재 확인"""
    assert _grep_proxy(r'/api/rag/kb/approve'), \
        "/api/rag/kb/approve route not found"
    assert _grep_proxy(r'/api/rag/kb/reject'), \
        "/api/rag/kb/reject route not found"


def test_auth_me_route_in_do_get():
    """do_GET에 /api/auth/me 라우트가 존재하는지 확인"""
    assert _grep_proxy(r'/api/auth/me'), \
        "/api/auth/me route not found in do_GET"


def test_kb_manager_static_route():
    """/kb_manager 정적 파일 라우트가 존재하는지 확인"""
    assert _grep_proxy(r"'/kb_manager'"), \
        "/kb_manager static route not found"


# ════════════════════════════════════════════════════
# CLI 진입점
# ════════════════════════════════════════════════════

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='RAG KB API 통합 테스트')
    parser.add_argument('--url', default='', help='테스트 대상 서버 URL (기본: 내부 포트 자동 기동)')
    parser.add_argument('--port', type=int, default=DEFAULT_PORT, help=f'테스트 서버 포트 (기본: {DEFAULT_PORT})')
    parser.add_argument('--no-server', action='store_true', help='서버를 직접 기동하지 않음 (이미 실행 중인 서버 사용)')
    args = parser.parse_args()

    target_url = args.url or f'http://localhost:{args.port}'

    if args.no_server or args.url:
        # 이미 실행 중인 서버 사용
        run_tests(target_url)
    else:
        # 서버 자동 기동
        if _is_port_open(args.port):
            print(f'[INFO] 포트 {args.port} 이미 사용 중 — 기존 서버 사용')
            run_tests(target_url)
        else:
            print(f'[INFO] proxy_server.py 기동 중 (포트 {args.port})...')
            try:
                proc = _start_server(args.port)
                print(f'[INFO] 서버 기동 완료')
                try:
                    run_tests(target_url)
                finally:
                    _stop_server(proc)
                    print('[INFO] 서버 종료')
            except RuntimeError as e:
                print(f'[ERROR] {e}')
                sys.exit(1)
