"""
rag_server.py — RAG 독립 HTTP 서비스 (저장소 분리 Phase 3, additive)
=====================================================================
RagRoutesMixin 을 **그대로 재사용**해 /api/rag/* 를 단독으로 서빙하는 BaseHTTPServer.
호스트(proxy_server)의 in-process 경로는 전혀 건드리지 않는다(믹스인 무변경 = 현재 동작 보존).

■ 인증 모델 (리버스 프록시 전제)
  호스트(proxy_server)가 쿠키 세션을 검증한 뒤 **신뢰헤더**로 변환해 전달한다:
    X-User-Id / X-User-Name / X-User-Role / X-User-Permissions
  이 서버는 그 헤더를 신뢰한다(쿠키/CORS 하드블로커 회피 — same-origin 유지).
  선택적 공유 시크릿(RAG_TRUST_SECRET): 설정 시 X-Rag-Trust 헤더와 일치해야 통과
  (호스트만 호출 가능하도록). 미설정 시 네트워크 경계(비공개 Cloud Run)에 의존.

■ 실행
  RUN_MODE=rag (entrypoint.sh) → python rag_server.py --port $PORT
  호스트는 RAG_SERVICE_URL 로 이 서비스를 가리킨다(미설정 시 호스트 in-process 유지).

■ 검증은 나중에
  현재는 additive — RAG_SERVICE_URL 미설정이면 활성화되지 않는다.
  PG/end-to-end 검증은 독립 서비스 배포(deploy-rag.ps1) 후 진행.
"""

import os
import sys
import io
import json
import logging
import argparse
import signal
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from urllib.parse import urlparse, unquote

from rag_routes import RagRoutesMixin

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("rag_server")

RAG_TRUST_SECRET = os.environ.get('RAG_TRUST_SECRET', '')

# schema_migrations 최신 버전 캐시 (기동 시 1회 조회, health 호출마다 DB 접근 방지)
_SCHEMA_VERSION_CACHE = "unknown"


class RagHandler(RagRoutesMixin, BaseHTTPRequestHandler):
    """RagRoutesMixin 단독 서빙. 믹스인이 요구하는 8개 헬퍼를 자체 구현(trust-header 인증)."""

    server_version = "RagService/1.0"

    # ── 응답 헬퍼 ────────────────────────────────────────────
    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header(
            'Access-Control-Allow-Headers',
            'Content-Type, X-User-Id, X-User-Name, X-User-Role, X-User-Permissions, '
            'X-Rag-Trust, X-Conversation-Id',
        )
        self.send_header('Access-Control-Max-Age', '86400')

    def _send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self._set_cors_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, code, message):
        body = json.dumps({"error": message}, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self._set_cors_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _add_log(self, msg):
        logger.info("%s", msg)

    # ── 인증: 신뢰헤더 기반 (호스트 프록시가 쿠키 검증 후 주입) ──
    def _trust_ok(self):
        if RAG_TRUST_SECRET:
            return self.headers.get('X-Rag-Trust', '') == RAG_TRUST_SECRET
        return True

    def _get_tester_info(self):
        if not self._trust_ok():
            return None
        uid = self.headers.get('X-User-Id', '')
        if not uid:
            return None
        # X-User-Name 은 URL 인코딩되어 옴(한글 이름의 latin-1 헤더 인코딩 실패 회피)
        name = unquote(self.headers.get('X-User-Name', '') or '') or uid
        return {
            'id': uid,
            'alias': name,
            'name': name,
            'org': '',
            'uid': uid,
            'role': self.headers.get('X-User-Role', 'tester'),
        }

    def _is_admin(self):
        return self._trust_ok() and self.headers.get('X-User-Role', '') == 'admin'

    def _user_permissions(self):
        raw = (self.headers.get('X-User-Permissions', '') or '').strip()
        if not raw:
            return []
        try:
            if raw.startswith('['):
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, list) else []
        except Exception:
            pass
        return [p.strip() for p in raw.split(',') if p.strip()]

    def _has_permission(self, perm):
        if not self._trust_ok():
            return False
        if self._is_admin():
            return True
        perms = self._user_permissions()
        return '*' in perms or perm in perms

    def _require_auth(self):
        if self._is_admin() or self._get_tester_info():
            return True
        self._send_error(403, '인증이 필요합니다 (신뢰헤더 누락)')
        return False

    # ── 라우팅 ───────────────────────────────────────────────
    def _route(self, method):
        parsed = urlparse(self.path)
        path = parsed.path
        # 헬스체크 (Cloud Run startup probe)
        if path in ('/', '/health', '/healthz'):
            return self._send_json(200, {
                "status": "ok",
                "service": "rag",
                "version": os.environ.get('K_REVISION', 'local'),
                "schema": _SCHEMA_VERSION_CACHE,
            })
        if not path.startswith('/api/rag/'):
            return self._send_error(404, 'RAG 서비스는 /api/rag/* 만 처리합니다')
        body = None
        if method in ('POST', 'PUT', 'DELETE'):
            length = int(self.headers.get('Content-Length', 0) or 0)
            body = self.rfile.read(length) if length else b''
        try:
            return self._handle_rag_route(method, path, parsed, body)
        except Exception as e:
            logger.exception("RAG route error: %s", e)
            try:
                self._send_error(500, f'RAG 처리 오류: {type(e).__name__}')
            except Exception:
                pass

    def do_GET(self):
        self._route('GET')

    def do_POST(self):
        self._route('POST')

    def do_PUT(self):
        self._route('PUT')

    def do_DELETE(self):
        self._route('DELETE')

    def do_OPTIONS(self):
        self.send_response(204)
        self._set_cors_headers()
        self.end_headers()

    def log_message(self, fmt, *args):
        try:
            logger.info("%s", args[0] if args else fmt)
        except Exception:
            pass


class _ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


def _query_schema_version() -> str:
    """schema_migrations 테이블의 최신 적용 버전을 조회해 반환.
    조회 실패/테이블 없음이면 "unknown"."""
    try:
        from dbcommon import get_conn, _p
        with get_conn() as (conn, cur):
            cur.execute(
                "SELECT version FROM schema_migrations "
                "ORDER BY version DESC LIMIT 1"
            )
            row = cur.fetchone()
        if row:
            return str(row[0]) if not hasattr(row, 'keys') else str(row['version'])
        return "unknown"
    except Exception as e:
        logger.warning("schema_version query failed: %s", e)
        return "unknown"


def main():
    global _SCHEMA_VERSION_CACHE

    # 한글 출력 (entrypoint 로 실행될 때만 — import 부작용 방지)
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
    except Exception:
        pass

    # DATABASE_URL 기동 가드: Cloud Run에서 누락 시 무음 SQLite 사용 사고 방지
    database_url = os.environ.get('DATABASE_URL', '')
    allow_sqlite = os.environ.get('RAG_ALLOW_SQLITE', '')
    if not database_url:
        if allow_sqlite:
            print(
                '[RAG-STARTUP] WARNING: DATABASE_URL 미설정 - RAG_ALLOW_SQLITE=1 로 SQLite 모드 허용',
                flush=True,
            )
        else:
            print(
                '[RAG-STARTUP] ERROR: DATABASE_URL 환경변수가 설정되지 않았습니다. '
                'Cloud Run 배포 시 필수입니다. '
                '로컬 개발 시 RAG_ALLOW_SQLITE=1 을 설정하면 SQLite 모드로 기동할 수 있습니다.',
                flush=True,
            )
            sys.exit(1)

    parser = argparse.ArgumentParser(description='RAG 독립 HTTP 서비스')
    parser.add_argument('--port', type=int, default=int(os.environ.get('PORT', 8080)))
    args = parser.parse_args()

    # RAG 전용 스키마 보장(rag_conversation_state 등) — best effort
    try:
        import rag_db
        rag_db.ensure_rag_schema()
    except Exception as e:
        logger.warning("ensure_rag_schema skip: %s", e)

    # schema_migrations 최신 버전 1회 조회 후 캐시 (health 호출마다 DB 접근 방지)
    _SCHEMA_VERSION_CACHE = _query_schema_version()
    print(f"[RAG-STARTUP] schema version: {_SCHEMA_VERSION_CACHE}", flush=True)

    print(f"[RAG-STARTUP] binding 0.0.0.0:{args.port}", flush=True)
    server = _ThreadedHTTPServer(('0.0.0.0', args.port), RagHandler)

    # SIGTERM graceful shutdown (Cloud Run 종료 시 in-flight SSE 정리)
    # serve_forever 스레드(메인)에서 server.shutdown() 직접 호출 시 데드락 발생
    # → 핸들러에서 별도 스레드로 shutdown 호출
    def _graceful(signum, frame):
        print('[RAG-SHUTDOWN] signal %s - graceful shutdown' % signum, flush=True)
        threading.Thread(target=server.shutdown, daemon=True).start()

    try:
        signal.signal(signal.SIGTERM, _graceful)
        signal.signal(signal.SIGINT, _graceful)
    except Exception as _e:
        logger.warning("signal handler 등록 실패 (무시): %s", _e)

    print(f"[RAG-STARTUP] RAG service ready on port {args.port}", flush=True)
    server.serve_forever()
    server.server_close()
    print('[RAG-SHUTDOWN] server closed', flush=True)


if __name__ == '__main__':
    main()
