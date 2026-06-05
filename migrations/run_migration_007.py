"""
run_migration_007.py — 한국어 어절 분리 content_tsv 재생성

목적:
  to_tsvector('simple', content) 에서 한국어 어절 조사 미분리로 인한
  BM25 키워드 매칭 실패 해소.

방식 (두 가지, --mode 로 선택):
  python  : reindex_korean_tsv.py Python 전처리 (권장, 조사 패턴 정교)
  sql     : 007_korean_tsvector.sql 직접 실행 (빠르나 SQL regexp 복잡)

DB 모드:
  PostgreSQL 전용 (tsvector SQLite 미지원)
  DATABASE_URL 환경변수 또는 DB_PASSWORD + DB_HOST 필요

사용법:
  python migrations/run_migration_007.py [--mode python|sql] [--batch-size 200]
"""

import os
import sys
import argparse
import traceback
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MIGRATIONS_DIR = Path(__file__).resolve().parent
SQL_PG = MIGRATIONS_DIR / "007_korean_tsvector.sql"
REINDEX_SCRIPT = REPO_ROOT / "reindex_korean_tsv.py"

DATABASE_URL = os.environ.get("DATABASE_URL", "")

# Secret Manager 분리 주입 지원
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


def _split_statements(sql_text: str) -> list:
    out = []
    for raw in sql_text.split(";"):
        s = raw.strip()
        if not s:
            continue
        lines = [l for l in s.splitlines()
                 if l.strip() and not l.strip().startswith("--")]
        if not lines:
            continue
        upper = s.upper().strip()
        if upper in ("BEGIN", "COMMIT", "ROLLBACK"):
            continue
        out.append(s)
    return out


def run_sql_mode(database_url: str) -> None:
    """007_korean_tsvector.sql 직접 실행 모드."""
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 미설치", file=sys.stderr)
        sys.exit(1)

    sql_text = SQL_PG.read_text(encoding="utf-8")
    stmts = _split_statements(sql_text)
    print(f"[007-SQL] {len(stmts)}개 statement 실행 ({SQL_PG.name})")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()
    try:
        for i, stmt in enumerate(stmts, 1):
            first = stmt.splitlines()[0][:80]
            print(f"  [{i:03d}] {first}...")
            cur.execute(stmt)
        conn.commit()
        print("[007-SQL] COMMIT 완료")
        _verify_postgres(cur)
    except Exception:
        conn.rollback()
        print("[007-SQL] 실패 — ROLLBACK", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def run_python_mode(database_url: str, batch_size: int) -> None:
    """reindex_korean_tsv.py Python 전처리 모드 (권장)."""
    if not REINDEX_SCRIPT.exists():
        print(f"[ERROR] {REINDEX_SCRIPT} 파일 없음", file=sys.stderr)
        sys.exit(1)

    print(f"[007-Python] {REINDEX_SCRIPT.name} 실행 (batch_size={batch_size})")
    env = os.environ.copy()
    env["DATABASE_URL"] = database_url

    result = subprocess.run(
        [sys.executable, str(REINDEX_SCRIPT), "--batch-size", str(batch_size)],
        env=env
    )
    if result.returncode != 0:
        print("[007-Python] 실패", file=sys.stderr)
        sys.exit(result.returncode)
    print("[007-Python] 완료")


def _verify_postgres(cur) -> None:
    """키워드 hits 검증."""
    keywords = ['기침', '심정지', '발열', '당뇨', '응급실']
    print("\n[007] 사후 키워드 hits:")
    for kw in keywords:
        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE content_tsv @@ plainto_tsquery('simple', %s)",
            (kw,)
        )
        n = cur.fetchone()[0]
        print(f"  '{kw}': {n} hits")


def main():
    parser = argparse.ArgumentParser(
        description="마이그레이션 007 — 한국어 content_tsv 재생성"
    )
    parser.add_argument("--mode", choices=["python", "sql"], default="python",
                        help="실행 모드: python(권장) 또는 sql (기본: python)")
    parser.add_argument("--batch-size", type=int, default=200,
                        help="Python 모드 배치 크기 (기본 200)")
    parser.add_argument("--database-url", default="",
                        help="PostgreSQL DSN (생략 시 환경변수 DATABASE_URL 사용)")
    args = parser.parse_args()

    db_url = args.database_url or DATABASE_URL

    print("=" * 60)
    print("  마이그레이션 007 — 한국어 content_tsv 재생성")
    print(f"  모드: {args.mode}")
    print("=" * 60)

    if not db_url:
        print("[ERROR] DATABASE_URL 또는 DB_PASSWORD+DB_HOST 환경변수가 필요합니다.", file=sys.stderr)
        print("        이 마이그레이션은 PostgreSQL 전용입니다.", file=sys.stderr)
        sys.exit(1)

    print("[MODE] PostgreSQL")

    if args.mode == "sql":
        run_sql_mode(db_url)
    else:
        run_python_mode(db_url, args.batch_size)

    print("=" * 60)
    print("  마이그레이션 007 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()
