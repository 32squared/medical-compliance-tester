"""
run_migration_009.py — Evidence-first Medical RAG 스펙 정합 스키마 보강 적용.

대상: 009_spec_modules.sql (PostgreSQL)
  - kb_sources: priority_rank/jurisdiction/medical_domain/institution/update_cycle
  - kb_chunks:  source_priority/population_tags/risk_tags/recommendation_grade/chunk_type/heading_path
  - rag_queries: answer_id/model_version/prompt_version/classification_json/evidence_pack_json
  - review_queue_items 테이블 + 인덱스
멱등성: 전부 ADD COLUMN IF NOT EXISTS / CREATE TABLE IF NOT EXISTS / 조건부 UPDATE → 재실행 안전.
DB 모드: PostgreSQL 전용 (Cloud SQL). DATABASE_URL 또는 DB_PASSWORD+DB_HOST 필요.
사용법: python migrations/run_migration_009.py
"""

import os
import sys
import traceback
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parent
SQL_PG = MIGRATIONS_DIR / "009_spec_modules.sql"

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    _pw = os.environ.get("DB_PASSWORD", "")
    _user = os.environ.get("DB_USER", "app_user")
    _name = os.environ.get("DB_NAME", "medical_app")
    _host = os.environ.get("DB_HOST", "")
    if _pw and _host:
        import urllib.parse
        DATABASE_URL = (
            f"postgresql://{_user}:{urllib.parse.quote(_pw, safe='')}@/{_name}?host={_host}"
        )


def _split(sql_text: str):
    """세미콜론 기준 분리 (009는 $$ 블록 없음)."""
    return [s.strip() for s in sql_text.split(";") if s.strip() and not s.strip().startswith("--")]


def main():
    if not DATABASE_URL:
        print("[009] ERROR: DATABASE_URL/DB_PASSWORD 미설정 — PostgreSQL 전용 마이그레이션", flush=True)
        sys.exit(1)
    try:
        import psycopg2
    except Exception as e:
        print(f"[009] ERROR: psycopg2 import 실패: {e}", flush=True)
        sys.exit(1)

    sql = SQL_PG.read_text(encoding="utf-8")
    statements = _split(sql)
    print(f"[009] {len(statements)}개 statement 적용 시작", flush=True)

    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = True
    ok = err = 0
    try:
        with conn.cursor() as cur:
            for i, stmt in enumerate(statements, 1):
                try:
                    cur.execute(stmt)
                    ok += 1
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" in msg or "duplicate" in msg:
                        ok += 1  # 멱등 재실행
                    else:
                        err += 1
                        print(f"[009] stmt#{i} ERR: {str(e)[:120]} | {stmt[:60]}", flush=True)
            # 검증
            cur.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name='kb_chunks' AND column_name='source_priority'"
            )
            has_sp = cur.fetchone() is not None
            cur.execute(
                "SELECT table_name FROM information_schema.tables WHERE table_name='review_queue_items'"
            )
            has_rq = cur.fetchone() is not None
        print(f"[009] 완료 ok={ok} err={err} | kb_chunks.source_priority={has_sp} review_queue_items={has_rq}",
              flush=True)
        sys.exit(0 if err == 0 else 2)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
