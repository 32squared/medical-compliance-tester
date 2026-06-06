"""
rag_db.py — RAG 전용 DB 함수
==============================
db.py 의 공유 연결 레이어(get_conn, _p, _ph, _row_to_dict, _now)를
import 해서 사용한다.
db.py 는 이 모듈을 import 하지 않는다(순환 임포트 방지).
호출처(rag_engine.py, review_queue.py 등)는 직접 이 모듈을 import 하라.

향후 RAG 스키마 변경은 ensure_rag_schema() 에 idempotent ALTER/CREATE 로
추가한다. 기존 db.py 의 kb_*/rag_queries DDL 은 건드리지 마라.
"""

import json
import uuid as _uuid
from datetime import datetime, timezone

from db import get_conn, _p, _row_to_dict


# ════════════════════════════════════════
#  스키마 훅 (향후 RAG 전용 DDL 추가 위치)
# ════════════════════════════════════════

# 스키마 보장 1회 가드 (프로세스 단위)
_RAG_SCHEMA_ENSURED = False


def ensure_rag_schema():
    """
    RAG 전용 스키마 변경 훅 (멱등 실행 가능).
    향후 RAG 전용 테이블/컬럼 추가는 여기에 idempotent ALTER/CREATE 문으로 작성한다.
    ※ 기존 db.py 의 kb_sources / kb_documents / kb_chunks / rag_queries DDL 은
       이 함수로 이동하지 말 것 (리스크 — 별도 작업으로).

    rag_conversation_state: RAG 응급 상태머신(emergency_state)을 RAG 소유 테이블에 보관.
    (기존엔 호스트 conversations 테이블을 직접 SELECT/UPDATE 했다 → 런타임 결합 해제)
    PG/SQLite 공용 DDL.
    """
    with get_conn() as (conn, cur):
        cur.execute(
            """CREATE TABLE IF NOT EXISTS rag_conversation_state (
                   conversation_id         TEXT PRIMARY KEY,
                   emergency_state         TEXT NOT NULL DEFAULT 'NORMAL',
                   emergency_redirected_at TEXT,
                   updated_at              TEXT NOT NULL
               )"""
        )
        conn.commit()


def _ensure_once():
    """rag_conversation_state 스키마를 프로세스당 1회 보장(멱등, 비차단)."""
    global _RAG_SCHEMA_ENSURED
    if _RAG_SCHEMA_ENSURED:
        return
    try:
        ensure_rag_schema()
        _RAG_SCHEMA_ENSURED = True
    except Exception:
        pass  # 다음 호출에서 재시도


def get_conversation_state(conversation_id: str) -> dict:
    """RAG 소유 rag_conversation_state 에서 emergency_state 조회.
    행이 없으면 {"emergency_state": "NORMAL"}. (예외 처리/로깅은 호출자 rag_engine 담당)"""
    _ensure_once()
    with get_conn() as (conn, cur):
        cur.execute(
            f"SELECT emergency_state FROM rag_conversation_state "
            f"WHERE conversation_id = {_p()}",
            (conversation_id,),
        )
        row = cur.fetchone()
    if row:
        rd = _row_to_dict(row)
        return {"emergency_state": rd.get("emergency_state") or "NORMAL"}
    return {"emergency_state": "NORMAL"}


def set_conversation_state(conversation_id: str, state: str) -> None:
    """RAG 소유 rag_conversation_state UPSERT.
    state="EMERGENCY_REDIRECTED" 일 때만 emergency_redirected_at=now 기록.
    NORMAL 전환 시 기존 redirected_at 은 COALESCE 로 보존(기존 동작 보존)."""
    _ensure_once()
    now = datetime.now(timezone.utc).isoformat()
    redirected_at = now if state == "EMERGENCY_REDIRECTED" else None
    with get_conn() as (conn, cur):
        cur.execute(
            f"INSERT INTO rag_conversation_state "
            f"(conversation_id, emergency_state, emergency_redirected_at, updated_at) "
            f"VALUES ({_p()},{_p()},{_p()},{_p()}) "
            f"ON CONFLICT (conversation_id) DO UPDATE SET "
            f"emergency_state = {_p()}, "
            f"emergency_redirected_at = COALESCE({_p()}, rag_conversation_state.emergency_redirected_at), "
            f"updated_at = {_p()}",
            (conversation_id, state, redirected_at, now,
             state, redirected_at, now),
        )
        conn.commit()


# ════════════════════════════════════════
#  Medical RAG 스펙 모듈 지원 (Review Queue / Audit)
# ════════════════════════════════════════

def add_review_item(data: dict):
    """고위험 답변 검수 큐(review_queue_items) 적재. 스키마 미적용/오류 시 None(비차단)."""
    try:
        item_id = "rvq-" + _uuid.uuid4().hex[:10]
        now = datetime.now(timezone.utc).isoformat()
        reasons = json.dumps(data.get("reasons", []), ensure_ascii=False)
        with get_conn() as (conn, cur):
            cur.execute(
                f"""INSERT INTO review_queue_items
                    (id, answer_id, rag_query_id, question, answer, priority,
                     assignee_role, reasons_json, status, created_at)
                    VALUES ({_p()},{_p()},{_p()},{_p()},{_p()},{_p()},{_p()},{_p()},{_p()},{_p()})""",
                (item_id, data.get("answer_id"), data.get("rag_query_id"),
                 data.get("question"), data.get("answer"), data.get("priority", "medium"),
                 data.get("assignee_role", "doctor"), reasons,
                 data.get("status", "pending"), now),
            )
            conn.commit()
        return item_id
    except Exception:
        return None


def update_rag_query_audit(rag_query_id: str, **fields):
    """rag_queries 감사 필드(answer_id/model_version/prompt_version/classification_json/
    evidence_pack_json) 갱신. 스키마 미적용/오류 시 무시(비차단)."""
    if not rag_query_id or not fields:
        return False
    allowed = {"answer_id", "model_version", "prompt_version",
               "classification_json", "evidence_pack_json"}
    cols = [k for k in fields if k in allowed]
    if not cols:
        return False
    try:
        sets = ", ".join(f"{c} = {_p()}" for c in cols)
        params = [fields[c] for c in cols] + [rag_query_id]
        with get_conn() as (conn, cur):
            cur.execute(f"UPDATE rag_queries SET {sets} WHERE id = {_p()}", params)
            conn.commit()
        return True
    except Exception:
        return False


def list_review_queue(status: str = "pending", limit: int = 50) -> list:
    """검수 큐 조회 (스펙 §8.4 review console용). 오류 시 빈 리스트."""
    try:
        with get_conn() as (conn, cur):
            cur.execute(
                f"""SELECT id, answer_id, question, priority, assignee_role,
                           reasons_json, status, created_at
                    FROM review_queue_items WHERE status = {_p()}
                    ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                             created_at DESC LIMIT {_p()}""",
                (status, limit),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]
    except Exception:
        return []
