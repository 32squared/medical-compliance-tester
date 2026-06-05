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

def ensure_rag_schema():
    """
    RAG 전용 스키마 변경 훅 (멱등 실행 가능).
    향후 RAG 전용 테이블/컬럼 추가는 여기에 idempotent ALTER/CREATE 문으로 작성한다.
    기존 db.py 의 kb_sources / kb_documents / kb_chunks / rag_queries DDL 은
    이 함수로 이동하지 말 것 (리스크).
    현재는 아무 작업도 수행하지 않는다.
    """
    pass


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
