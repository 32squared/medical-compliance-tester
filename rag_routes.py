"""
rag_routes.py — RAG 라우트 믹스인
====================================
proxy_server.ProxyHandler에서 RAG 관련 핸들러 메서드와
/api/rag/* 디스패처를 분리한 믹스인 클래스.

순환 임포트 방지:
  - proxy_server 는 이 모듈을 import 한다.
  - 이 모듈은 proxy_server 를 import 하면 안 된다.
  - 로깅은 self._add_log() (ProxyHandler 클래스 메서드) 로 위임한다.
"""

import json
import os
import re
from datetime import datetime, timezone
from urllib.parse import parse_qs

import dbcommon as db  # 4-E 수렴: db facade 대신 dbcommon 직접 사용 (db.X 속성 참조 호환 alias)

# ── RAG 피처 플래그 (proxy_server 와 동일 로직, 독립 정의) ──
# 순환 임포트를 피하기 위해 proxy_server.RAG_ENABLED 를 import 하지 않고
# 동일한 환경변수를 직접 읽는다.
RAG_ENABLED = os.environ.get("RAG_ENABLED", "false").lower() in ("true", "1", "yes", "on")


class RagRoutesMixin:
    """
    RAG 라우트 믹스인.
    ProxyHandler 의 첫 번째 베이스 클래스로 사용한다.

    self.* 로 접근하는 ProxyHandler 메서드·속성:
      _send_json, _send_error, _require_auth, _is_admin,
      _has_permission, _get_tester_info, _set_cors_headers,
      send_response, send_header, end_headers, wfile, path,
      _add_log (classmethod)
    모두 ProxyHandler 에 정의돼 있으므로 믹스인에서는 self 로 접근한다.
    """

    # ────────────────────────────────────────────────────────────
    # 디스패처 — do_POST/PUT/DELETE/GET 에서 /api/rag/ 를 위임
    # ────────────────────────────────────────────────────────────

    def _handle_rag_route(self, method, path, parsed, body):
        """
        /api/rag/* 라우트를 method 별로 분기한다.
        parsed : urlparse 결과 (GET 쿼리스트링용)
        body   : bytes (GET 은 None 가능)
        기존 do_POST/PUT/DELETE/GET 에 흩어진 if 블록의 순서·권한을
        그대로 재현한다.
        """
        # ── POST ──────────────────────────────────────────────
        if method == 'POST':
            if path == '/api/rag/kb/documents':
                if not self._require_auth():
                    return
                if not (self._is_admin() or self._has_permission('manage_kb')):
                    return self._send_error(403, 'manage_kb 권한이 필요합니다')
                return self._rag_kb_create_document(body)

            if path == '/api/rag/kb/approve':
                if not self._require_auth():
                    return
                if not (self._is_admin() or self._has_permission('manage_kb')):
                    return self._send_error(403, 'manage_kb 권한이 필요합니다')
                return self._rag_kb_approve_document(body)

            if path == '/api/rag/kb/reject':
                if not self._require_auth():
                    return
                if not (self._is_admin() or self._has_permission('manage_kb')):
                    return self._send_error(403, 'manage_kb 권한이 필요합니다')
                return self._rag_kb_reject_document(body)

            m_kb_reembed = re.match(r'^/api/rag/kb/documents/([^/]+)/reembed$', path)
            if m_kb_reembed:
                if not self._require_auth():
                    return
                if not (self._is_admin() or self._has_permission('manage_kb')):
                    return self._send_error(403, 'manage_kb 권한이 필요합니다')
                return self._rag_kb_reembed_document(m_kb_reembed.group(1))

            if path == '/api/rag/chat':
                return self._rag_chat(body)

            return self._send_error(404, 'Not Found')

        # ── PUT ───────────────────────────────────────────────
        if method == 'PUT':
            m_kb_doc_put = re.match(r'^/api/rag/kb/documents/([^/]+)$', path)
            if m_kb_doc_put:
                if not self._require_auth():
                    return
                if not (self._is_admin() or self._has_permission('manage_kb')):
                    return self._send_error(403, 'manage_kb 권한이 필요합니다')
                return self._rag_kb_update_document(m_kb_doc_put.group(1), body)

            return self._send_error(404, 'Not Found')

        # ── DELETE ────────────────────────────────────────────
        if method == 'DELETE':
            m_kb_doc_del = re.match(r'^/api/rag/kb/documents/([^/]+)$', path)
            if m_kb_doc_del:
                if not self._require_auth():
                    return
                if not (self._is_admin() or self._has_permission('manage_kb')):
                    return self._send_error(403, 'manage_kb 권한이 필요합니다')
                return self._rag_kb_delete_document(m_kb_doc_del.group(1))

            return self._send_error(404, 'Not Found')

        # ── GET ───────────────────────────────────────────────
        if method == 'GET':
            if path == '/api/rag/result':
                return self._rag_get_result(parsed)

            if path == '/api/rag/kb/sources':
                if not self._require_auth():
                    return
                return self._rag_kb_list_sources()

            if path == '/api/rag/kb/documents':
                if not self._require_auth():
                    return
                return self._rag_kb_list_documents(parsed.query)

            m_kb_doc_reembed = re.match(r'^/api/rag/kb/documents/([^/]+)/reembed$', path)
            if m_kb_doc_reembed:
                # reembed 는 POST 전용 — GET 에서 매칭 시 흘려보냄 (404 방지용 early return 없음)
                pass
            else:
                m_kb_doc = re.match(r'^/api/rag/kb/documents/([^/]+)$', path)
                if m_kb_doc:
                    if not self._require_auth():
                        return
                    return self._rag_kb_get_document(m_kb_doc.group(1))

            return self._send_error(404, 'Not Found')

        return self._send_error(405, 'Method Not Allowed')

    # ────────────────────────────────────────────────────────────
    # RAG 채팅 SSE API
    # ────────────────────────────────────────────────────────────

    def _rag_chat(self, body):
        """POST /api/rag/chat — RAG 응답 생성 SSE 엔드포인트

        요청 body:
          {
            "query": "발열이 나요",
            "conversation_id": "conv-xxx",   (없으면 UUID 자동 생성)
            "provider_id": null,              (없으면 환경변수 기본값)
            "top_k": 5,
            "enable_guardrails": true
          }

        SSE 응답:
          data: {"type":"INFO","data":{"search_results":[...]}}
          data: {"type":"GENERATION","text":"..."}
          data: {"type":"STOP","text":"...","rag_query_id":"...","citations":[...],...}
          data: {"type":"ERROR","message":"..."}  (에러 시)

        SQLite 모드에서는 503 반환.
        """
        # ── 0. 피처 플래그: 비활성 시 차단 (운영 다크) ──
        if not RAG_ENABLED:
            return self._send_json(503, {
                "error": "RAG 기능이 현재 비활성화되어 있습니다.",
                "code": "RAG_DISABLED",
                "hint": "RAG_ENABLED=true 환경변수로 활성화하세요.",
            })

        # ── 1. 인증 (Admin 또는 Tester 모두 허용) ──
        if not self._require_auth():
            return

        # ── 2. 요청 파싱 ──
        try:
            payload = json.loads(body.decode('utf-8')) if body else {}
        except Exception as e:
            return self._send_json(400, {"error": f"Invalid JSON: {e}"})

        query = (payload.get('query') or '').strip()
        if not query:
            return self._send_json(400, {"error": "query is required"})

        # conversation_id — 없으면 UUID 생성
        import uuid as _uuid_mod
        conversation_id = (payload.get('conversation_id') or '').strip()
        if not conversation_id:
            conversation_id = str(_uuid_mod.uuid4())

        provider_id = payload.get('provider_id') or None
        top_k = int(payload.get('top_k') or 5)
        enable_guardrails = bool(payload.get('enable_guardrails', True))

        # ── 3. SQLite 모드 차단 ──
        if not db._use_postgres:
            return self._send_json(503, {
                "error": (
                    "RAG features require PostgreSQL with pgvector. "
                    "Set DATABASE_URL to enable."
                ),
                "code": "RAG_REQUIRES_POSTGRES",
            })

        # ── 4. conversation 행 보장 (이력 표시용 — 없으면 INSERT, 있으면 그대로) ──
        #     emergency_state 는 RAG 소유 rag_conversation_state 가 관리하므로 여기서
        #     호스트 conversations 컬럼에 쓰지 않는다(컬럼 DEFAULT 'NORMAL' 사용).
        #     conversation 행 생성 자체의 호스트 이관은 Phase 3(리버스 프록시)에서 처리.
        try:
            tester_info = self._get_tester_info()
            user_id = tester_info['id'] if tester_info else 'admin'
            now_ts = datetime.now(timezone.utc).isoformat()
            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"INSERT INTO conversations "
                    f"(id, user_id, user_name, title, env, conversation_strid, "
                    f"created_at, updated_at) "
                    f"VALUES ({db._ph(8)}) "
                    f"ON CONFLICT (id) DO NOTHING",
                    (
                        conversation_id,
                        user_id,
                        tester_info.get('name', user_id) if tester_info else 'admin',
                        query[:80],  # 제목으로 질의 첫 80자 사용
                        'rag',
                        '',
                        now_ts,
                        now_ts,
                    ),
                )
                conn.commit()
        except Exception as e:
            self._add_log(f"[RAG-CHAT] conversation INSERT 오류 (무시): {e}")

        # ── 5. SSE 헤더 전송 ──
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('X-Accel-Buffering', 'no')
        self.send_header('Connection', 'keep-alive')
        self._set_cors_headers()
        self.end_headers()

        # ── 6. generate_response 스트리밍 (요청 스레드에서 실행) ──
        # Cloud Run에서는 백그라운드 스레드가 진행되지 못하므로(요청 스레드만 CPU 확보)
        # generate_response는 '요청 핸들러 스레드'에서 그대로 돌린다(diag로 40초 완주 확인).
        # 진짜 '행(hang)' 원인 = self.wfile.write가 클라이언트 지연으로 무한 블록되면
        # generate_response가 yield에서 멈춰 생성 자체가 정지했던 것.
        # 해결: 클라이언트 소켓에 write 타임아웃을 걸어, 블록 시 OSError(timeout)로 빠져나와
        # '드레인 모드'(쓰기 없이 생성만 끝까지 진행)로 전환 → 결과를 rag_queries에 저장.
        # 프론트는 STOP을 못 받아도 /api/rag/result 폴링으로 항상 복구한다.
        try:
            self.connection.settimeout(30)  # write 블록 상한(클라이언트 지연 감지)
        except Exception:
            pass
        try:
            from rag_engine import generate_response

            client_gone = False
            for event in generate_response(
                query=query,
                conversation_id=conversation_id,
                provider_id=provider_id,
                top_k=top_k,
                enable_guardrails=enable_guardrails,
            ):
                if client_gone:
                    continue  # 쓰기 없이 생성 완주까지 진행(결과 저장 보장)
                try:
                    line = "data: " + json.dumps(event, ensure_ascii=False) + "\n\n"
                    self.wfile.write(line.encode('utf-8'))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError) as _we:
                    # 끊김(BrokenPipe) 또는 지연으로 write 타임아웃(OSError) → 드레인 전환
                    client_gone = True
                    self._add_log(
                        f"[RAG-CHAT] 전송 중단(끊김/지연: {type(_we).__name__}) — 생성은 끝까지 진행, 결과 저장→폴링 복구"
                    )
            if client_gone:
                self._add_log("[RAG-CHAT] 생성 완주 — 결과 rag_queries 저장됨(폴링 복구 가능)")

        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            self._add_log(f"[RAG-CHAT] 연결 오류(생성은 진행 후 종료): {e}")
        except Exception as e:
            self._add_log(f"[RAG-CHAT] 스트리밍 오류: {e}")

    def _rag_get_result(self, parsed):
        """GET /api/rag/result?conversation_id=X&query=...&since_sec=N

        SSE truncation 복구용 엔드포인트. 클라이언트 연결이 중간에 끊겨도
        서버는 generate_response를 끝까지 소비해 rag_queries에 결과를 저장하므로,
        프론트는 이 엔드포인트를 폴링해 답변·인용(source_url 포함)·가드레일을 복구한다.

        해당 conversation의 '최근 since_sec초 내' + (query 일치 시) 최신 1건을 반환.
          - status=ready : 결과 있음
          - status=pending : 아직 생성 중(또는 없음) → 프론트가 재폴링
        """
        if not RAG_ENABLED:
            return self._send_json(503, {"error": "RAG 비활성", "code": "RAG_DISABLED"})
        if not self._require_auth():
            return
        if not db._use_postgres:
            return self._send_json(503, {
                "error": "RAG requires PostgreSQL", "code": "RAG_REQUIRES_POSTGRES",
            })
        try:
            from urllib.parse import parse_qs
            qs = parse_qs(parsed.query or "")
            conversation_id = (qs.get('conversation_id', [''])[0] or '').strip()
            if not conversation_id:
                return self._send_json(400, {"error": "conversation_id is required"})
            query_text = (qs.get('query', [''])[0] or '').strip()
            try:
                since_sec = int(qs.get('since_sec', ['300'])[0])
            except Exception:
                since_sec = 300
            since_sec = max(10, min(since_sec, 1800))

            from datetime import datetime, timezone, timedelta
            floor_iso = (datetime.now(timezone.utc) - timedelta(seconds=since_sec)).isoformat()

            sql = (
                f"SELECT id, response_text, citations_json, guardrail_action, "
                f"evidence_quality, created_at FROM rag_queries "
                f"WHERE conversation_id = {db._p()} AND created_at >= {db._p()} "
            )
            params = [conversation_id, floor_iso]
            if query_text:
                sql += f"AND query_text = {db._p()} "
                params.append(query_text)
            sql += "ORDER BY created_at DESC LIMIT 1"

            with db.get_conn() as (conn, cur):
                cur.execute(sql, tuple(params))
                row = cur.fetchone()

            if not row:
                return self._send_json(200, {"status": "pending"})
            rd = dict(row)
            citations = []
            try:
                _c = rd.get('citations_json')
                citations = json.loads(_c) if isinstance(_c, str) else (_c or [])
            except Exception:
                citations = []
            return self._send_json(200, {
                "status": "ready",
                "rag_query_id": rd.get('id'),
                "answer": rd.get('response_text') or '',
                "citations": citations,
                "guardrail_action": rd.get('guardrail_action') or 'pass',
                "evidence_quality": rd.get('evidence_quality'),
                "created_at": str(rd.get('created_at')),
            })
        except Exception as e:
            self._add_log(f"[RAG-RESULT] 조회 오류: {e}")
            return self._send_json(500, {"error": str(e)})

    # ────────────────────────────────────────────────────────────
    # RAG KB 관리 API
    # ────────────────────────────────────────────────────────────

    def _rag_kb_list_sources(self):
        """GET /api/rag/kb/sources — kb_sources 전체 목록"""
        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    "SELECT id, name, source_type, license, url, update_frequency, "
                    "last_updated_at, is_active, created_at "
                    "FROM kb_sources WHERE is_active = 1 ORDER BY name"
                )
                rows = cur.fetchall()
            sources = []
            for r in rows:
                if isinstance(r, dict):
                    sources.append(dict(r))
                else:
                    sources.append({
                        'id': r[0], 'name': r[1], 'source_type': r[2],
                        'license': r[3], 'url': r[4], 'update_frequency': r[5],
                        'last_updated_at': r[6], 'is_active': r[7], 'created_at': r[8],
                    })
            return self._send_json(200, sources)
        except Exception as e:
            self._add_log(f"[RAG-KB] sources 조회 실패: {e}")
            return self._send_error(500, f'KB 소스 조회 실패: {str(e)}')

    def _rag_kb_list_documents(self, query_string):
        """GET /api/rag/kb/documents — 문서 목록 (필터·페이지네이션)"""
        params = parse_qs(query_string)
        status_filter = params.get('status', [None])[0]
        source_id_filter = params.get('source_id', [None])[0]
        symptom_filter = params.get('symptom', [None])[0]
        q_filter = params.get('q', [None])[0]
        try:
            page = max(1, int(params.get('page', ['1'])[0]))
            page_size = max(1, min(100, int(params.get('page_size', ['20'])[0])))
        except ValueError:
            page, page_size = 1, 20

        # draft/rejected는 manage_kb 권한 필요
        if status_filter in ('draft', 'rejected'):
            if not (self._is_admin() or self._has_permission('manage_kb')):
                return self._send_error(403, 'draft/rejected 문서 조회는 manage_kb 권한이 필요합니다')

        try:
            conditions = []
            args = []
            if status_filter:
                conditions.append(f"d.status = {db._p()}")
                args.append(status_filter)
            if source_id_filter:
                conditions.append(f"d.source_id = {db._p()}")
                args.append(source_id_filter)
            if symptom_filter:
                conditions.append(f"d.metadata_json LIKE {db._p()}")
                args.append(f'%{symptom_filter}%')
            if q_filter:
                conditions.append(f"d.title LIKE {db._p()}")
                args.append(f'%{q_filter}%')

            where_clause = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
            offset = (page - 1) * page_size

            count_sql = f"""
                SELECT COUNT(*) FROM kb_documents d
                {where_clause}
            """
            select_sql = f"""
                SELECT d.id, d.title, d.source_id, s.name AS source_name,
                       d.status, d.evidence_level, d.metadata_json,
                       d.author_id, d.approved_by, d.approved_at, d.rejected_reason,
                       d.version, d.created_at, d.updated_at,
                       (SELECT COUNT(*) FROM kb_chunks c WHERE c.document_id = d.id) AS chunks_count
                FROM kb_documents d
                LEFT JOIN kb_sources s ON d.source_id = s.id
                {where_clause}
                ORDER BY d.created_at DESC
                LIMIT {db._p()} OFFSET {db._p()}
            """
            list_args = args + [page_size, offset]

            with db.get_conn() as (conn, cur):
                cur.execute(count_sql, args)
                total_row = cur.fetchone()
                total = total_row[0] if total_row else 0

                cur.execute(select_sql, list_args)
                rows = cur.fetchall()

            documents = []
            for r in rows:
                if isinstance(r, dict):
                    doc = dict(r)
                else:
                    doc = {
                        'id': r[0], 'title': r[1], 'source_id': r[2],
                        'source_name': r[3], 'status': r[4], 'evidence_level': r[5],
                        'metadata_json': r[6], 'author_id': r[7], 'approved_by': r[8],
                        'approved_at': r[9], 'rejected_reason': r[10], 'version': r[11],
                        'created_at': r[12], 'updated_at': r[13], 'chunks_count': r[14],
                    }
                # metadata_json 파싱
                raw_meta = doc.get('metadata_json', '{}')
                doc['metadata'] = db._pg_json_loads(raw_meta) if raw_meta else {}
                doc.pop('metadata_json', None)
                documents.append(doc)

            return self._send_json(200, {
                'documents': documents,
                'total': total,
                'page': page,
                'page_size': page_size,
            })
        except Exception as e:
            self._add_log(f"[RAG-KB] documents 조회 실패: {e}")
            return self._send_error(500, f'KB 문서 조회 실패: {str(e)}')

    def _rag_kb_get_document(self, doc_id):
        """GET /api/rag/kb/documents/{id} — 문서 메타 + chunks"""
        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    "SELECT d.id, d.title, d.source_id, s.name AS source_name, "
                    "d.content_md, d.status, d.evidence_level, d.metadata_json, "
                    "d.author_id, d.approved_by, d.approved_at, d.rejected_reason, "
                    "d.version, d.created_at, d.updated_at "
                    "FROM kb_documents d "
                    "LEFT JOIN kb_sources s ON d.source_id = s.id "
                    f"WHERE d.id = {db._p()}",
                    (doc_id,)
                )
                row = cur.fetchone()
                if not row:
                    return self._send_error(404, f'문서를 찾을 수 없습니다: {doc_id}')

                if isinstance(row, dict):
                    doc = dict(row)
                else:
                    doc = {
                        'id': row[0], 'title': row[1], 'source_id': row[2],
                        'source_name': row[3], 'content_md': row[4], 'status': row[5],
                        'evidence_level': row[6], 'metadata_json': row[7],
                        'author_id': row[8], 'approved_by': row[9], 'approved_at': row[10],
                        'rejected_reason': row[11], 'version': row[12],
                        'created_at': row[13], 'updated_at': row[14],
                    }

                # chunks 조회
                cur.execute(
                    "SELECT id, chunk_index, content, section_path_json, token_count, "
                    "evidence_country, evidence_topic, regulatory_korea, topic_keywords_json, "
                    "created_at "
                    "FROM kb_chunks "
                    f"WHERE document_id = {db._p()} ORDER BY chunk_index",
                    (doc_id,)
                )
                chunk_rows = cur.fetchall()

            raw_meta = doc.get('metadata_json', '{}')
            doc['metadata'] = db._pg_json_loads(raw_meta) if raw_meta else {}
            doc.pop('metadata_json', None)

            chunks = []
            for cr in chunk_rows:
                if isinstance(cr, dict):
                    ch = dict(cr)
                else:
                    ch = {
                        'id': cr[0], 'chunk_index': cr[1], 'content': cr[2],
                        'section_path_json': cr[3], 'token_count': cr[4],
                        'evidence_country': cr[5], 'evidence_topic': cr[6],
                        'regulatory_korea': cr[7], 'topic_keywords_json': cr[8],
                        'created_at': cr[9],
                    }
                raw_sp = ch.pop('section_path_json', None)
                raw_kw = ch.pop('topic_keywords_json', None)
                ch['section_path'] = db._pg_json_loads(raw_sp) if raw_sp else []
                ch['topic_keywords'] = db._pg_json_loads(raw_kw) if raw_kw else []
                chunks.append(ch)

            doc['chunks'] = chunks
            doc['chunks_count'] = len(chunks)
            return self._send_json(200, doc)
        except Exception as e:
            self._add_log(f"[RAG-KB] document 단건 조회 실패: {e}")
            return self._send_error(500, f'KB 문서 조회 실패: {str(e)}')

    def _rag_kb_create_document(self, body):
        """POST /api/rag/kb/documents — 신규 문서 ingest"""
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send_error(400, '잘못된 JSON')

        title = (payload.get('title') or '').strip()
        content_md = (payload.get('content_md') or '').strip()
        source_id = (payload.get('source_id') or '').strip()

        if not title:
            return self._send_error(400, 'title은 필수입니다')
        if not content_md:
            return self._send_error(400, 'content_md는 필수입니다')
        if not source_id:
            return self._send_error(400, 'source_id는 필수입니다')

        metadata = payload.get('metadata', {})
        status = payload.get('status', 'draft')
        evidence_country = payload.get('evidence_country', 'KR')
        evidence_topic = payload.get('evidence_topic')
        regulatory_korea = bool(payload.get('regulatory_korea', False))
        topic_keywords = payload.get('topic_keywords') or []

        tester = self._get_tester_info()
        author_id = tester['id'] if tester else (None if not self._is_admin() else 'admin')

        try:
            from kb_ingest import ingest_document
            result = ingest_document(
                title=title,
                content_md=content_md,
                source_id=source_id,
                metadata=metadata,
                evidence_country=evidence_country,
                evidence_topic=evidence_topic,
                regulatory_korea=regulatory_korea,
                topic_keywords=topic_keywords,
                upsert=False,
                status=status,
                author_id=author_id,
            )
            self._add_log(
                f"[RAG-KB] 문서 생성: title={title}, doc_id={result.get('document_id')}, "
                f"chunks={result.get('chunks_count')}"
            )
            return self._send_json(201, {
                'document_id': result['document_id'],
                'chunks_count': result['chunks_count'],
                'status': result.get('status', status),
            })
        except ValueError as e:
            return self._send_error(400, str(e))
        except Exception as e:
            self._add_log(f"[RAG-KB] 문서 생성 실패: {e}")
            return self._send_error(500, f'문서 생성 실패: {str(e)}')

    def _rag_kb_update_document(self, doc_id, body):
        """PUT /api/rag/kb/documents/{id} — 문서 메타 수정 (content_md 수정 시 /reembed 별도)"""
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send_error(400, '잘못된 JSON')

        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"SELECT id, version FROM kb_documents WHERE id = {db._p()}",
                    (doc_id,)
                )
                row = cur.fetchone()
                if not row:
                    return self._send_error(404, f'문서를 찾을 수 없습니다: {doc_id}')

            now_str = db._now()
            set_parts = []
            set_args = []

            if 'title' in payload:
                set_parts.append(f"title = {db._p()}")
                set_args.append(payload['title'])
            if 'content_md' in payload:
                set_parts.append(f"content_md = {db._p()}")
                set_args.append(payload['content_md'])
            if 'status' in payload:
                set_parts.append(f"status = {db._p()}")
                set_args.append(payload['status'])
            if 'evidence_level' in payload:
                set_parts.append(f"evidence_level = {db._p()}")
                set_args.append(payload['evidence_level'])
            if 'metadata' in payload:
                set_parts.append(f"metadata_json = {db._p()}")
                set_args.append(json.dumps(payload['metadata'], ensure_ascii=False))
            if 'source_id' in payload:
                set_parts.append(f"source_id = {db._p()}")
                set_args.append(payload['source_id'])

            if not set_parts:
                return self._send_error(400, '수정할 필드가 없습니다')

            set_parts.append(f"updated_at = {db._p()}")
            set_args.append(now_str)
            set_args.append(doc_id)

            update_sql = f"UPDATE kb_documents SET {', '.join(set_parts)} WHERE id = {db._p()}"
            with db.get_conn() as (conn, cur):
                cur.execute(update_sql, set_args)

            self._add_log(f"[RAG-KB] 문서 수정: doc_id={doc_id}")
            return self._send_json(200, {'updated': True, 'document_id': doc_id})
        except Exception as e:
            self._add_log(f"[RAG-KB] 문서 수정 실패: {e}")
            return self._send_error(500, f'문서 수정 실패: {str(e)}')

    def _rag_kb_delete_document(self, doc_id):
        """DELETE /api/rag/kb/documents/{id} — 문서 삭제 (CASCADE → chunks도 삭제)"""
        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"SELECT id FROM kb_documents WHERE id = {db._p()}",
                    (doc_id,)
                )
                row = cur.fetchone()
                if not row:
                    return self._send_error(404, f'문서를 찾을 수 없습니다: {doc_id}')

                cur.execute(
                    f"DELETE FROM kb_documents WHERE id = {db._p()}",
                    (doc_id,)
                )

            self._add_log(f"[RAG-KB] 문서 삭제: doc_id={doc_id}")
            return self._send_json(200, {'deleted': True, 'document_id': doc_id})
        except Exception as e:
            self._add_log(f"[RAG-KB] 문서 삭제 실패: {e}")
            return self._send_error(500, f'문서 삭제 실패: {str(e)}')

    def _rag_kb_approve_document(self, body):
        """POST /api/rag/kb/approve — 문서 승인 (pending_review → active)"""
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send_error(400, '잘못된 JSON')

        doc_id = (payload.get('document_id') or '').strip()
        if not doc_id:
            return self._send_error(400, 'document_id는 필수입니다')

        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"SELECT id, status FROM kb_documents WHERE id = {db._p()}",
                    (doc_id,)
                )
                row = cur.fetchone()
                if not row:
                    return self._send_error(404, f'문서를 찾을 수 없습니다: {doc_id}')

                current_status = row['status'] if isinstance(row, dict) else row[1]
                if current_status not in ('pending_review', 'draft'):
                    return self._send_error(400,
                        f"상태가 pending_review/draft인 문서만 승인 가능합니다 (현재: {current_status})")

            tester = self._get_tester_info()
            approver_id = tester['id'] if tester else 'admin'
            now_str = db._now()

            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"""UPDATE kb_documents
                        SET status = 'active', approved_by = {db._p()},
                            approved_at = {db._p()}, updated_at = {db._p()}
                        WHERE id = {db._p()}""",
                    (approver_id, now_str, now_str, doc_id)
                )

            self._add_log(f"[RAG-KB] 문서 승인: doc_id={doc_id}, approver={approver_id}")
            return self._send_json(200, {'approved': True, 'document_id': doc_id})
        except Exception as e:
            self._add_log(f"[RAG-KB] 문서 승인 실패: {e}")
            return self._send_error(500, f'문서 승인 실패: {str(e)}')

    def _rag_kb_reject_document(self, body):
        """POST /api/rag/kb/reject — 문서 반려"""
        try:
            payload = json.loads(body.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._send_error(400, '잘못된 JSON')

        doc_id = (payload.get('document_id') or '').strip()
        reason = (payload.get('reason') or '').strip()

        if not doc_id:
            return self._send_error(400, 'document_id는 필수입니다')
        if not reason:
            return self._send_error(400, 'reason은 필수입니다')

        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"SELECT id FROM kb_documents WHERE id = {db._p()}",
                    (doc_id,)
                )
                row = cur.fetchone()
                if not row:
                    return self._send_error(404, f'문서를 찾을 수 없습니다: {doc_id}')

            now_str = db._now()
            with db.get_conn() as (conn, cur):
                cur.execute(
                    f"""UPDATE kb_documents
                        SET status = 'rejected', rejected_reason = {db._p()},
                            updated_at = {db._p()}
                        WHERE id = {db._p()}""",
                    (reason, now_str, doc_id)
                )

            self._add_log(f"[RAG-KB] 문서 반려: doc_id={doc_id}")
            return self._send_json(200, {'rejected': True, 'document_id': doc_id})
        except Exception as e:
            self._add_log(f"[RAG-KB] 문서 반려 실패: {e}")
            return self._send_error(500, f'문서 반려 실패: {str(e)}')

    def _rag_kb_reembed_document(self, doc_id):
        """POST /api/rag/kb/documents/{id}/reembed — 기존 청크 삭제 후 재임베딩"""
        try:
            with db.get_conn() as (conn, cur):
                cur.execute(
                    "SELECT id, title, content_md, source_id, metadata_json, status, author_id "
                    f"FROM kb_documents WHERE id = {db._p()}",
                    (doc_id,)
                )
                row = cur.fetchone()
                if not row:
                    return self._send_error(404, f'문서를 찾을 수 없습니다: {doc_id}')

                if isinstance(row, dict):
                    doc = dict(row)
                else:
                    doc = {
                        'id': row[0], 'title': row[1], 'content_md': row[2],
                        'source_id': row[3], 'metadata_json': row[4],
                        'status': row[5], 'author_id': row[6],
                    }

            raw_meta = doc.get('metadata_json', '{}')
            metadata = db._pg_json_loads(raw_meta) if raw_meta else {}

            from kb_ingest import ingest_document
            result = ingest_document(
                title=doc['title'],
                content_md=doc['content_md'],
                source_id=doc['source_id'],
                metadata=metadata,
                upsert=True,
                status=doc.get('status', 'active'),
                author_id=doc.get('author_id'),
            )
            self._add_log(
                f"[RAG-KB] 재임베딩: doc_id={doc_id}, chunks={result.get('chunks_count')}"
            )
            return self._send_json(200, {
                'reembedded': True,
                'document_id': doc_id,
                'chunks_count': result.get('chunks_count', 0),
            })
        except Exception as e:
            self._add_log(f"[RAG-KB] 재임베딩 실패: {e}")
            return self._send_error(500, f'재임베딩 실패: {str(e)}')
