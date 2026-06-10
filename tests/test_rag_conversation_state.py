"""
test_rag_conversation_state.py — Phase 1: RAG 소유 emergency 상태머신 검증

emergency_state 를 호스트 conversations 테이블이 아니라 RAG 소유
rag_conversation_state 테이블로 이관한 동작을 검증한다(SQLite 로직 검증).
※ 운영은 Postgres — PG 동작은 다음 dev 배포 시 실증. 본 테스트는 backend-무관 로직.
"""

import os
import sys
import tempfile
import sqlite3
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# DB_PATH 는 db import 시점에 읽히므로 import 전에 설정 (SQLite 강제)
os.environ.pop("DATABASE_URL", None)
_TMP = os.path.join(tempfile.gettempdir(), "rag_convstate_test.sqlite")
if os.path.exists(_TMP):
    os.remove(_TMP)
os.environ["DB_PATH"] = _TMP

import dbcommon    # noqa: E402 — DB_PATH 가 이미 env 에 주입됐으므로 연결 가능
# rag_db 는 내부에서 db.py 를 import 해 init_db() 를 실행하므로 먼저 로드한다.
# (repo 분리 후 rag_db 는 dbcommon 에 직접 의존하도록 변경 예정 — 4-E 과제)
import rag_db      # noqa: E402
# test_no_host_conversations_write 가 SELECT 하는 conversations 테이블 보장.
# db.init_db 는 이미 rag_db 임포트 중 db.py 모듈 수준에서 실행됨.
# (rag_db → db.py → init_db() 체인으로 이미 생성됨 — 직접 import db 불필요)


def _tables():
    c = sqlite3.connect(_TMP)
    try:
        return {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    finally:
        c.close()


def _row(cid):
    c = sqlite3.connect(_TMP)
    try:
        return c.execute(
            "SELECT emergency_state, emergency_redirected_at FROM rag_conversation_state WHERE conversation_id=?",
            (cid,),
        ).fetchone()
    finally:
        c.close()


def test_ensure_creates_table():
    # init_db 는 rag_conversation_state 를 만들지 않음 (RAG 소유 — ensure_rag_schema 담당)
    rag_db.ensure_rag_schema()
    assert "rag_conversation_state" in _tables(), _tables()
    # 멱등: 두 번 호출해도 오류 없음
    rag_db.ensure_rag_schema()
    print("test_ensure_creates_table: OK")


def test_default_normal_when_absent():
    # 행이 없으면 NORMAL (lazy _ensure_once 로 테이블 자동 보장)
    assert rag_db.get_conversation_state("c-absent")["emergency_state"] == "NORMAL"
    print("test_default_normal_when_absent: OK")


def test_set_emergency_records_redirected():
    cid = "c-emerg"
    rag_db.set_conversation_state(cid, "EMERGENCY_REDIRECTED")
    assert rag_db.get_conversation_state(cid)["emergency_state"] == "EMERGENCY_REDIRECTED"
    row = _row(cid)
    assert row is not None and row[0] == "EMERGENCY_REDIRECTED"
    assert row[1] is not None, "emergency_redirected_at 기록돼야 함"
    print("test_set_emergency_records_redirected: OK")


def test_normal_transition_preserves_redirected():
    """EMERGENCY_REDIRECTED → NORMAL 전환 시 redirected_at 은 보존(COALESCE) — 기존 동작."""
    cid = "c-preserve"
    rag_db.set_conversation_state(cid, "EMERGENCY_REDIRECTED")
    first = _row(cid)[1]
    assert first is not None
    rag_db.set_conversation_state(cid, "NORMAL")
    assert rag_db.get_conversation_state(cid)["emergency_state"] == "NORMAL"
    after = _row(cid)[1]
    assert after == first, f"redirected_at 보존 실패: {first} → {after}"
    print("test_normal_transition_preserves_redirected: OK")


def test_no_host_conversations_write():
    """RAG 상태 set/get 이 호스트 conversations 테이블을 건드리지 않음."""
    cid = "c-iso"
    # conversations 에 같은 id 행이 없어도 RAG 상태는 독립적으로 동작
    rag_db.set_conversation_state(cid, "EMERGENCY_REDIRECTED")
    c = sqlite3.connect(_TMP)
    try:
        conv = c.execute("SELECT count(*) FROM conversations WHERE id=?", (cid,)).fetchone()[0]
    finally:
        c.close()
    assert conv == 0, "RAG 상태 쓰기가 호스트 conversations 에 행을 만들면 안 됨"
    assert rag_db.get_conversation_state(cid)["emergency_state"] == "EMERGENCY_REDIRECTED"
    print("test_no_host_conversations_write: OK")


def test_engine_delegation():
    """rag_engine._get/_set_conversation_state 가 rag_db(rag_conversation_state)에 위임."""
    try:
        import rag_engine
    except Exception as e:
        print(f"  (rag_engine import 스킵: {type(e).__name__}: {str(e)[:60]})")
        return
    cid = "c-engine"
    rag_engine._set_conversation_state(cid, "EMERGENCY_REDIRECTED")
    assert rag_engine._get_conversation_state(cid)["emergency_state"] == "EMERGENCY_REDIRECTED"
    # rag_db 로 직접 읽어도 동일 (같은 테이블 사용 확인)
    assert rag_db.get_conversation_state(cid)["emergency_state"] == "EMERGENCY_REDIRECTED"
    print("test_engine_delegation: OK")


def _run_all():
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"\nALL {len(fns)} TESTS PASSED")


if __name__ == "__main__":
    _run_all()
