"""
run_migration_005.py — rag_queries에 Phase A Retrieval Gate 컬럼 추가

DB 모드 자동 감지:
  - DATABASE_URL 환경변수 있음 → PostgreSQL
  - DATABASE_URL 없음           → SQLite

사용법:
  python migrations/run_migration_005.py [--db-path /path/to/app.db]
"""

import os
import sys
import sqlite3
import argparse
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MIGRATIONS_DIR = Path(__file__).resolve().parent
SQL_PG     = MIGRATIONS_DIR / "005_evidence_grounding.sql"
SQL_SQLITE = MIGRATIONS_DIR / "005_evidence_grounding_sqlite.sql"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Secret Manager 분리 주입 방식 지원
# DB_PASSWORD(Secret) + DB_USER + DB_NAME + DB_HOST 로 DATABASE_URL 조합
if not DATABASE_URL:
    _pw   = os.environ.get("DB_PASSWORD", "")
    _user = os.environ.get("DB_USER", "app_user")
    _name = os.environ.get("DB_NAME", "medical_app")
    _host = os.environ.get("DB_HOST", "")
    if _pw and _host:
        import urllib.parse
        DATABASE_URL = (
            f"postgresql://{_user}:{urllib.parse.quote(_pw, safe='')}@/{_name}"
            f"?host={_host}"
        )

_NEW_COLUMNS = [
    "evidence_quality",
    "retrieval_top1_score",
    "retrieval_chunk_count",
    "retrieval_weighted_score",
    "gate_decision",
    "blocked_reasons",
    "claims_json",
    "verified_at",
]


def _split_statements(sql_text: str) -> list:
    out = []
    for raw in sql_text.split(";"):
        s = raw.strip()
        if not s:
            continue
        lines = [l for l in s.splitlines() if l.strip() and not l.strip().startswith("--")]
        if not lines:
            continue
        upper = s.upper().strip()
        if upper in ("BEGIN", "COMMIT", "ROLLBACK"):
            continue
        out.append(s)
    return out


def run_postgres(database_url: str) -> None:
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 미설치", file=sys.stderr)
        sys.exit(1)

    sql_text = SQL_PG.read_text(encoding="utf-8")
    stmts = _split_statements(sql_text)
    print(f"[PG] {len(stmts)}개 statement 실행 ({SQL_PG.name})")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        for i, stmt in enumerate(stmts, 1):
            first = stmt.splitlines()[0][:80]
            print(f"  [{i:03d}] {first}...")
            cur.execute(stmt)
        conn.commit()
        print("[PG] 마이그레이션 005 완료")
        _verify_postgres(cur)
    except Exception:
        conn.rollback()
        print("[PG] 실패 — ROLLBACK", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def _verify_postgres(cur):
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'rag_queries'
          AND column_name = ANY(ARRAY[
              'evidence_quality', 'retrieval_top1_score', 'retrieval_chunk_count',
              'retrieval_weighted_score', 'gate_decision', 'blocked_reasons',
              'claims_json', 'verified_at'
          ])
        ORDER BY column_name
    """)
    found = {r[0] for r in cur.fetchall()}
    missing = set(_NEW_COLUMNS) - found
    if missing:
        print(f"[WARN] 누락 컬럼: {missing}")
    else:
        print(f"[PG] rag_queries 신규 컬럼 8개 모두 확인: {sorted(found)}")

    # 인덱스 확인
    cur.execute("""
        SELECT indexname FROM pg_indexes
        WHERE tablename = 'rag_queries'
          AND indexname IN (
              'idx_rag_queries_gate_decision',
              'idx_rag_queries_evidence_quality'
          )
        ORDER BY indexname
    """)
    idx_found = [r[0] for r in cur.fetchall()]
    print(f"[PG] 신규 인덱스 확인: {idx_found}")


def run_sqlite(db_path: str) -> None:
    sql_text = SQL_SQLITE.read_text(encoding="utf-8")
    print(f"[SQLite] {db_path} ({SQL_SQLITE.name})")
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        # ALTER TABLE ADD COLUMN은 IF NOT EXISTS 미지원 → 개별 실행 + duplicate 무시
        stmts = _split_statements(sql_text)
        for stmt in stmts:
            try:
                conn.execute(stmt)
            except sqlite3.OperationalError as e:
                if "duplicate column" in str(e).lower():
                    print(f"  [SKIP] 이미 존재: {stmt[:60]}")
                else:
                    raise
        conn.commit()
        print("[SQLite] 마이그레이션 005 완료")
        _verify_sqlite(conn)
    except Exception:
        print("[SQLite] 실패", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


def _verify_sqlite(conn):
    cur = conn.execute("PRAGMA table_info(rag_queries)")
    cols = {r[1] for r in cur.fetchall()}
    missing = set(_NEW_COLUMNS) - cols
    if missing:
        print(f"[WARN] 누락 컬럼: {missing}")
    else:
        print(f"[SQLite] rag_queries 신규 컬럼 8개 모두 확인")

    idx_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='rag_queries'"
        " AND name IN ('idx_rag_queries_gate_decision','idx_rag_queries_evidence_quality')"
    ).fetchall()
    print(f"[SQLite] 신규 인덱스 확인: {[r[0] for r in idx_rows]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=str(REPO_ROOT / "app.db"))
    parser.add_argument("--database-url", default="")
    args = parser.parse_args()

    db_url = args.database_url or DATABASE_URL
    print("=" * 60)
    print("  마이그레이션 005 — rag_queries Phase A Retrieval Gate 컬럼")
    print("=" * 60)
    if db_url:
        print("[MODE] PostgreSQL")
        run_postgres(db_url)
    else:
        print(f"[MODE] SQLite → {args.db_path}")
        run_sqlite(args.db_path)
    print("=" * 60)
    print("  마이그레이션 005 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()
