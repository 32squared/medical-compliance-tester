"""
run_migration_006.py — kb_chunks.content_tsv 일괄 재생성

목적: BM25 sparse 검색이 0건 반환되는 원인인 content_tsv NULL 값을
      to_tsvector('simple', content) 로 일괄 채운다.

DB 모드 자동 감지:
  - DATABASE_URL 환경변수 있음 → PostgreSQL
  - DATABASE_URL 없음           → 진단만 출력 (SQLite는 tsvector 미지원)

사용법:
  python migrations/run_migration_006.py
"""

import os
import sys
import argparse
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MIGRATIONS_DIR = Path(__file__).resolve().parent
SQL_PG = MIGRATIONS_DIR / "006_rebuild_content_tsv.sql"

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


def _split_statements(sql_text: str) -> list:
    """BEGIN/COMMIT 제거 후 실행 가능한 statement 목록 반환."""
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


def run_postgres(database_url: str) -> None:
    try:
        import psycopg2
    except ImportError:
        print("[ERROR] psycopg2 미설치", file=sys.stderr)
        sys.exit(1)

    print(f"[PG] SQL 파일: {SQL_PG.name}")

    conn = psycopg2.connect(database_url)
    conn.autocommit = False
    cur = conn.cursor()

    try:
        # ── 사전 진단 ──────────────────────────────────────────────────
        cur.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(content_tsv) AS with_tsv,
                   COUNT(*) FILTER (WHERE content_tsv IS NULL) AS missing
              FROM kb_chunks
        """)
        row = cur.fetchone()
        total, with_tsv, missing = row
        print(f"[006] 사전 진단: total={total}, with_tsv={with_tsv}, missing={missing}")

        cur.execute("""
            SELECT COUNT(*) FROM kb_chunks
             WHERE content_tsv @@ plainto_tsquery('simple', '발열')
        """)
        hits_before = cur.fetchone()[0]
        print(f"[006] 사전 키워드 hits(발열): {hits_before}")

        if missing == 0:
            print("[006] content_tsv가 이미 모두 채워져 있습니다. UPDATE 스킵.")
        else:
            # ── 일괄 UPDATE (단일 트랜잭션) ────────────────────────────
            print(f"[006] UPDATE 시작 — {missing}개 행 대상...")
            cur.execute("""
                UPDATE kb_chunks
                   SET content_tsv = to_tsvector('simple', COALESCE(content, ''))
                 WHERE content IS NOT NULL
            """)
            updated = cur.rowcount
            print(f"[006] UPDATE 완료 — 영향 행수: {updated}")

        conn.commit()
        print("[PG] COMMIT 완료")

        # ── 사후 검증 ──────────────────────────────────────────────────
        _verify_postgres(cur, total)

    except Exception:
        conn.rollback()
        print("[PG] 실패 — ROLLBACK", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)
    finally:
        cur.close()
        conn.close()


def _verify_postgres(cur, total_before: int) -> None:
    cur.execute("""
        SELECT COUNT(*) AS total,
               COUNT(content_tsv) AS with_tsv
          FROM kb_chunks
    """)
    row = cur.fetchone()
    total_after, with_tsv_after = row

    rate = round(with_tsv_after / total_after * 100, 1) if total_after > 0 else 0.0
    print(f"[006] 사후 검증: total={total_after}, with_tsv={with_tsv_after}, tsv_rate={rate}%")

    cur.execute("""
        SELECT COUNT(*) FROM kb_chunks
         WHERE content_tsv @@ plainto_tsquery('simple', '발열')
    """)
    hits_after = cur.fetchone()[0]
    print(f"[006] 사후 키워드 hits(발열): {hits_after}")

    # 합격 기준
    if rate < 99.9:
        print(f"[WARN] tsv_rate={rate}% — 일부 content IS NULL 행 존재 가능 (content NULL은 제외 정상)")
    else:
        print(f"[PG] content_tsv 적재율 {rate}% — 정상")

    if hits_after == 0:
        print("[WARN] '발열' 키워드 hits=0 — content에 '발열' 텍스트가 없을 수 있음")
    else:
        print(f"[PG] '발열' 키워드 hits={hits_after} — BM25 검색 정상")


def main():
    parser = argparse.ArgumentParser(
        description="마이그레이션 006 — kb_chunks.content_tsv 일괄 재생성"
    )
    parser.add_argument("--database-url", default="")
    args = parser.parse_args()

    db_url = args.database_url or DATABASE_URL

    print("=" * 60)
    print("  마이그레이션 006 — kb_chunks.content_tsv 재생성")
    print("=" * 60)

    if not db_url:
        print("[ERROR] DATABASE_URL 또는 DB_PASSWORD+DB_HOST 환경변수가 필요합니다.", file=sys.stderr)
        print("        SQLite는 tsvector를 지원하지 않아 이 마이그레이션은 PostgreSQL 전용입니다.", file=sys.stderr)
        sys.exit(1)

    print("[MODE] PostgreSQL")
    run_postgres(db_url)

    print("=" * 60)
    print("  마이그레이션 006 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()
