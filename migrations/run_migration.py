"""
run_migration.py — RAG Phase 1 DB 마이그레이션 실행기

DB 모드 자동 감지:
  - DATABASE_URL 환경변수 있음  → PostgreSQL 모드로 001_rag_tables.sql 실행
  - DATABASE_URL 없음           → SQLite 모드로 001_rag_tables_sqlite.sql 실행

사용법:
  python migrations/run_migration.py [--db-path /path/to/app.db]

Cloud Run Job 컨테이너에서 실행할 때는 DATABASE_URL이 주입되므로 자동으로 PostgreSQL 모드.
"""

import os
import sys
import sqlite3
import argparse
import traceback
from pathlib import Path

# 상위 디렉토리를 sys.path에 추가 (db.py, config.py import 경로)
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MIGRATIONS_DIR = Path(__file__).resolve().parent
SQL_PG     = MIGRATIONS_DIR / "001_rag_tables.sql"
SQL_SQLITE = MIGRATIONS_DIR / "001_rag_tables_sqlite.sql"

DATABASE_URL = os.environ.get("DATABASE_URL", "")


# ──────────────────────────────────────────────
#  헬퍼
# ──────────────────────────────────────────────

def _split_statements(sql_text: str) -> list:
    """SQL 텍스트를 개별 statement 리스트로 분리.
    BEGIN / COMMIT은 별도 처리하므로 제거. 빈 줄·주석만인 fragment 제거.
    """
    statements = []
    for raw in sql_text.split(";"):
        stmt = raw.strip()
        if not stmt:
            continue
        # 주석만인 경우 스킵
        lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
        if not lines:
            continue
        # BEGIN / COMMIT 은 psycopg2 autocommit=False 환경에서 직접 제어하므로 제외
        upper = stmt.upper().strip()
        if upper in ("BEGIN", "COMMIT", "ROLLBACK"):
            continue
        statements.append(stmt)
    return statements


# ──────────────────────────────────────────────
#  PostgreSQL 실행
# ──────────────────────────────────────────────

def run_postgres(database_url: str) -> None:
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 미설치. pip install psycopg2-binary 실행 후 재시도하세요.", file=sys.stderr)
        sys.exit(1)

    sql_text = SQL_PG.read_text(encoding="utf-8")
    statements = _split_statements(sql_text)

    print(f"[PG] {len(statements)}개 statement 실행 예정 ({SQL_PG.name})")
    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        for i, stmt in enumerate(statements, 1):
            first_line = stmt.splitlines()[0][:80]
            print(f"  [{i:03d}] {first_line}...")
            try:
                cur.execute(stmt)
            except psycopg2.errors.DuplicateObject:
                # 이미 존재하는 extension / index 등은 무시 (멱등)
                conn.rollback()
                conn.autocommit = False
                cur = conn.cursor()
            except Exception as e:
                conn.rollback()
                print(f"[FAIL] statement {i} 실패: {e}", file=sys.stderr)
                print(f"       SQL: {stmt[:200]}", file=sys.stderr)
                raise

        conn.commit()
        print("[PG] 마이그레이션 완료 (COMMIT)")

        # 검증
        _verify_postgres(cur)

    except Exception:
        print("[PG] 마이그레이션 실패 — ROLLBACK", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def _verify_postgres(cur) -> None:
    """8개 테이블 + 시드 데이터 존재 여부 확인"""
    expected_tables = [
        "kb_sources", "kb_documents", "kb_chunks",
        "llm_providers", "rag_queries", "kb_feedback",
        "embedding_providers", "email_notifications",
    ]
    cur.execute("""
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = ANY(%s)
    """, (expected_tables,))
    found = {row[0] for row in cur.fetchall()}
    missing = set(expected_tables) - found

    if missing:
        print(f"[WARN] 누락 테이블: {missing}", file=sys.stderr)
    else:
        print(f"[PG] 8개 테이블 모두 존재 확인")

    # conversations ALTER 확인
    cur.execute("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'conversations'
          AND column_name IN ('emergency_state', 'emergency_redirected_at')
    """)
    conv_cols = {row[0] for row in cur.fetchall()}
    if len(conv_cols) == 2:
        print("[PG] conversations.emergency_state / emergency_redirected_at 컬럼 확인")
    else:
        print(f"[WARN] conversations 컬럼 누락: {set(['emergency_state','emergency_redirected_at']) - conv_cols}")

    # 시드 데이터 확인
    cur.execute("SELECT slot, model_id FROM embedding_providers WHERE slot = 'default'")
    ep = cur.fetchone()
    if ep:
        print(f"[PG] embedding_providers 시드: slot={ep[0]}, model={ep[1]}")
    else:
        print("[WARN] embedding_providers 시드 없음")

    cur.execute("SELECT count(*) FROM llm_providers WHERE id IN ('openai_gpt5','openai_gpt5_mini')")
    lp_count = cur.fetchone()[0]
    print(f"[PG] llm_providers 시드: {lp_count}행 (기대: 2)")

    # HNSW 인덱스 확인
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'kb_chunks'
          AND indexname = 'idx_kb_chunks_emb_primary'
    """)
    hnsw = cur.fetchone()
    if hnsw:
        print("[PG] HNSW 인덱스 idx_kb_chunks_emb_primary 존재 확인")
    else:
        print("[WARN] HNSW 인덱스 미생성 (kb_chunks가 비어있으면 정상)")


# ──────────────────────────────────────────────
#  SQLite 실행
# ──────────────────────────────────────────────

def run_sqlite(db_path: str) -> None:
    sql_text = SQL_SQLITE.read_text(encoding="utf-8")

    print(f"[SQLite] {db_path} 대상으로 마이그레이션 실행 ({SQL_SQLITE.name})")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=DELETE")

    try:
        # BEGIN/COMMIT 포함된 전체 스크립트를 executescript로 실행
        conn.executescript(sql_text)

        # SQLite ALTER TABLE: IF NOT EXISTS 미지원이므로 별도 처리
        _sqlite_alter_conversations(conn)

        conn.commit()
        print("[SQLite] 마이그레이션 완료 (COMMIT)")
        _verify_sqlite(conn)

    except Exception:
        print("[SQLite] 마이그레이션 실패", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


def _sqlite_alter_conversations(conn: sqlite3.Connection) -> None:
    """SQLite ALTER TABLE ADD COLUMN (오류 무시 — 이미 있으면 패스)"""
    alters = [
        "ALTER TABLE conversations ADD COLUMN emergency_state TEXT DEFAULT 'NORMAL'",
        "ALTER TABLE conversations ADD COLUMN emergency_redirected_at TEXT",
    ]
    for sql in alters:
        try:
            conn.execute(sql)
            print(f"  [ALTER] {sql[:60]}")
        except sqlite3.OperationalError as e:
            if "duplicate column" in str(e).lower():
                print(f"  [SKIP] 이미 존재: {sql[:60]}")
            else:
                raise


def _verify_sqlite(conn: sqlite3.Connection) -> None:
    """8개 테이블 + 시드 데이터 확인"""
    expected = [
        "kb_sources", "kb_documents", "kb_chunks",
        "llm_providers", "rag_queries", "kb_feedback",
        "embedding_providers", "email_notifications",
    ]
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name IN ({})".format(
            ",".join(f"'{t}'" for t in expected)
        )
    )
    found = {row[0] for row in cur.fetchall()}
    missing = set(expected) - found
    if missing:
        print(f"[WARN] 누락 테이블: {missing}")
    else:
        print(f"[SQLite] 8개 테이블 모두 존재 확인")

    # conversations 컬럼 확인
    cur2 = conn.execute("PRAGMA table_info(conversations)")
    cols = {row[1] for row in cur2.fetchall()}
    if "emergency_state" in cols and "emergency_redirected_at" in cols:
        print("[SQLite] conversations.emergency_state / emergency_redirected_at 확인")
    else:
        print("[WARN] conversations 컬럼 누락")

    # 시드 데이터
    row = conn.execute("SELECT slot, model_id FROM embedding_providers WHERE slot='default'").fetchone()
    if row:
        print(f"[SQLite] embedding_providers 시드: slot={row[0]}, model={row[1]}")
    else:
        print("[WARN] embedding_providers 시드 없음")

    count = conn.execute(
        "SELECT count(*) FROM llm_providers WHERE id IN ('openai_gpt5','openai_gpt5_mini')"
    ).fetchone()[0]
    print(f"[SQLite] llm_providers 시드: {count}행 (기대: 2)")


# ──────────────────────────────────────────────
#  main
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RAG Phase 1 마이그레이션 실행기")
    parser.add_argument(
        "--db-path",
        default=str(REPO_ROOT / "app.db"),
        help="SQLite DB 경로 (SQLite 모드 시 사용, 기본: app.db)"
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="PostgreSQL 접속 URL (미지정 시 DATABASE_URL 환경변수 사용)"
    )
    args = parser.parse_args()

    db_url = args.database_url or DATABASE_URL

    print("=" * 60)
    print("  RAG Phase 1 마이그레이션 (001_rag_tables)")
    print("=" * 60)

    if db_url:
        print(f"[MODE] PostgreSQL")
        run_postgres(db_url)
    else:
        print(f"[MODE] SQLite → {args.db_path}")
        run_sqlite(args.db_path)

    print("=" * 60)
    print("  마이그레이션 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()
