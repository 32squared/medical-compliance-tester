#!/usr/bin/env python3
"""
CORS 프록시 서버
================
브라우저 → localhost:9000 → SKIX API 로 요청을 중계합니다.
채팅 테스터 HTML에서 직접 외부 API를 호출하면 CORS로 차단되므로,
이 프록시를 거쳐서 요청합니다.

사용법:
  python proxy_server.py
  python proxy_server.py --port 9000
"""

import argparse
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError
import ssl
import os

# 스크립트가 있는 폴더 기준으로 파일 경로 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


class ProxyHandler(BaseHTTPRequestHandler):
    """SKIX API 프록시 핸들러"""

    # HTTP/1.1 사용 (chunked encoding 지원)
    protocol_version = 'HTTP/1.1'

    def do_OPTIONS(self):
        """CORS preflight 처리"""
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_POST(self):
        """POST 요청 프록시"""
        try:
            # 요청 본문 읽기
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length) if content_length else b''

            # 대상 URL 구성 (X-Target-URL 헤더에서 가져옴)
            target_url = self.headers.get('X-Target-URL', '')
            if not target_url:
                self._send_error(400, '누락: X-Target-URL 헤더')
                return

            # 전달할 헤더 구성
            forward_headers = {}
            for key in ['X-API-Key', 'X-tenant-Domain', 'X-Api-UID', 'Content-Type']:
                val = self.headers.get(key)
                if val:
                    forward_headers[key] = val
            forward_headers['Accept'] = 'text/event-stream'

            # SSL 컨텍스트 (인증서 검증)
            ctx = ssl.create_default_context()

            # 요청 전송
            req = Request(
                url=target_url,
                data=body,
                headers=forward_headers,
                method='POST',
            )

            resp = urlopen(req, context=ctx, timeout=120)

            # SSE 스트리밍 응답 중계
            self.send_response(resp.status)
            self._set_cors_headers()
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('X-Accel-Buffering', 'no')
            self.end_headers()

            # 스트리밍 전달 (chunked encoding 없이 직접 전송)
            while True:
                chunk = resp.read(1024)
                if not chunk:
                    break
                self.wfile.write(chunk)
                self.wfile.flush()

        except HTTPError as e:
            error_body = e.read().decode('utf-8', errors='replace')
            self._send_error(e.code, error_body[:500])
        except URLError as e:
            self._send_error(502, f'프록시 연결 실패: {str(e)}')
        except Exception as e:
            self._send_error(500, f'프록시 오류: {str(e)}')

    def do_GET(self):
        """GET 요청 — 상태 확인 또는 정적 파일 서빙"""
        if self.path == '/health':
            self.send_response(200)
            self._set_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "message": "프록시 서버 작동 중"}).encode())
            return

        # 정적 파일 서빙 (HTML, JS, CSS) — 절대경로 사용
        file_map = {
            '/': os.path.join(BASE_DIR, 'chat_tester.html'),
            '/chat_tester.html': os.path.join(BASE_DIR, 'chat_tester.html'),
            '/demo_report.html': os.path.join(BASE_DIR, 'reports', 'demo_report.html'),
        }
        file_path = file_map.get(self.path)
        if file_path and os.path.exists(file_path):
            with open(file_path, 'rb') as f:
                data = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return

        self.send_response(404)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers',
                         'Content-Type, X-API-Key, X-tenant-Domain, X-Api-UID, X-Target-URL')
        self.send_header('Access-Control-Max-Age', '86400')

    def _send_error(self, code, message):
        body = json.dumps({"error": message}, ensure_ascii=False).encode()
        self.send_response(code)
        self._set_cors_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        """로그 포맷 커스터마이즈"""
        print(f"[프록시] {args[0]}")


def main():
    parser = argparse.ArgumentParser(description='SKIX API CORS 프록시 서버')
    parser.add_argument('--port', type=int, default=9000, help='포트 번호 [기본: 9000]')
    args = parser.parse_args()

    server = HTTPServer(('0.0.0.0', args.port), ProxyHandler)
    print(f"""
╔══════════════════════════════════════════════════╗
║  나만의 주치의 — CORS 프록시 서버                    ║
║  http://localhost:{args.port}                         ║
║                                                  ║
║  채팅 테스터:  http://localhost:{args.port}/              ║
║  상태 확인:    http://localhost:{args.port}/health         ║
║                                                  ║
║  Ctrl+C 로 종료                                   ║
╚══════════════════════════════════════════════════╝
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n서버를 종료합니다.")
        server.server_close()


if __name__ == '__main__':
    main()
