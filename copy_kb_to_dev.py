"""
copy_kb_to_dev.py — 운영 KB를 dev DB로 복제 (Dev RAG 테스트 셋팅용).

운영(SRC, 읽기전용) → dev(DST, 쓰기)로 kb_sources/kb_documents/kb_chunks를
**스키마까지 동기화**해 복제한다(운영에만 있는 컬럼을 dev에 ADD). 재수집·재임베딩
없이 즉시 dev에서 RAG 인용 테스트 가능.

연결:
  SRC = DATABASE_URL        (운영 medical_app, 읽기만)
  DST = DST_DATABASE_URL    (dev medical_app_dev, 쓰기)

특성:
- pgvector 확장 + kb_chunks 테이블/인덱스 보장
- 스키마 동기화: 운영의 누락 컬럼을 format_type 그대로 dev에 ALTER ADD
- 깨끗한 재복제: dev kb_* TRUNCATE 후 운영 데이터 전량 복사(멱등하게 동일 결과)
- vector/tsvector 컬럼은 ::text 읽기 / ::<udt> 쓰기로 보존
"""

from __future__ import annotations

import os
import sys

import psycopg2

_TABLES = ["kb_sources", "kb_documents", "kb_chunks"]   # FK 순서
_BATCH = 500
_SPECIAL_UDT = {"vector", "tsvector"}

_KB_CHUNKS_DDL = """CREATE TABLE IF NOT EXISTS kb_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    section_path TEXT,
    embedding_primary vector(1536),
    embedding_secondary vector(1024),
    embedding_primary_model TEXT NOT NULL DEFAULT '',
    embedding_secondary_model TEXT,
    secondary_indexed_at TEXT,
    evidence_country TEXT,
    evidence_topic TEXT,
    regulatory_korea BOOLEAN DEFAULT FALSE,
    topic_keywords TEXT DEFAULT '[]',
    token_count INTEGER,
    symptom_tags TEXT DEFAULT '[]',
    severity TEXT,
    content_tsv tsvector,
    created_at TEXT NOT NULL
)"""
_KB_CHUNKS_IDX = [
    "CREATE INDEX IF NOT EXISTS idx_kb_chunks_emb_primary ON kb_chunks "
    "USING hnsw (embedding_primary vector_cosine_ops) WITH (m = 16, ef_construction = 64)",
    "CREATE INDEX IF NOT EXISTS idx_kb_chunks_tsv ON kb_chunks USING gin(content_tsv)",
    "CREATE INDEX IF NOT EXISTS idx_kb_chunks_document ON kb_chunks(document_id)",
]


def _typed_columns(cur, table):
    """[(name, format_type, udt_name)] — 정확한 타입 문자열(vector(1536) 등)."""
    cur.execute(
        "SELECT a.attname, pg_catalog.format_type(a.atttypid, a.atttypmod), t.typname "
        "FROM pg_attribute a "
        "JOIN pg_class c ON a.attrelid = c.oid "
        "JOIN pg_type t ON a.atttypid = t.oid "
        "WHERE c.relname = %s AND a.attnum > 0 AND NOT a.attisdropped "
        "ORDER BY a.attnum",
        (table,),
    )
    return cur.fetchall()


def _ensure_dev_base(dc, conn):
    dc.execute("CREATE EXTENSION IF NOT EXISTS vector")
    dc.execute(_KB_CHUNKS_DDL)
    for idx in _KB_CHUNKS_IDX:
        dc.execute(idx)
    conn.commit()
    print("  [dev] pgvector + kb_chunks 보장", flush=True)


def _sync_schema(sc, dc, conn, table):
    """운영에만 있는 컬럼을 dev에 ALTER ADD (타입 보존). dev 컬럼 목록 반환."""
    prod_cols = _typed_columns(sc, table)
    dc.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name=%s",
        (table,),
    )
    dev_have = {r[0] for r in dc.fetchall()}
    added = []
    for name, ftype, _udt in prod_cols:
        if name not in dev_have:
            dc.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "{name}" {ftype}')
            added.append(f"{name} {ftype}")
    if added:
        conn.commit()
        print(f"  [sync] {table} 컬럼 추가: {', '.join(added)}", flush=True)
    # 복제 대상 = 운영 컬럼 순서
    return [(n, u) for (n, _f, u) in prod_cols]


def main():
    src_url = os.environ.get("DATABASE_URL")
    dst_url = os.environ.get("DST_DATABASE_URL")
    if not src_url or not dst_url:
        print("[copy_kb] ERROR: DATABASE_URL(운영) + DST_DATABASE_URL(dev) 필요", flush=True)
        sys.exit(1)
    if "medical_app_dev" not in dst_url:
        print("[copy_kb] ERROR: 안전장치 — DST는 medical_app_dev 여야 함", flush=True)
        sys.exit(1)

    print("===KB_COPY_BEGIN===", flush=True)
    src = psycopg2.connect(src_url); src.set_session(readonly=True)
    dst = psycopg2.connect(dst_url)
    sc = src.cursor(); dc = dst.cursor()

    _ensure_dev_base(dc, dst)

    # 1) 스키마 동기화
    table_cols = {t: _sync_schema(sc, dc, dst, t) for t in _TABLES}

    # 2) 깨끗한 재복제 — 역순 TRUNCATE (FK)
    for t in reversed(_TABLES):
        dc.execute(f"TRUNCATE TABLE {t} CASCADE")
    dst.commit()

    # 3) 운영 → dev 복사
    for t in _TABLES:
        cols = table_cols[t]
        names = [c[0] for c in cols]
        special = {c[0]: c[1] for c in cols if c[1] in _SPECIAL_UDT}
        sel = ", ".join((f'"{n}"::text' if n in special else f'"{n}"') for n in names)
        ph = ", ".join((f"%s::{special[n]}" if n in special else "%s") for n in names)
        ins = f'INSERT INTO {t} ({", ".join(chr(34)+n+chr(34) for n in names)}) VALUES ({ph})'
        sc.execute(f"SELECT {sel} FROM {t}")
        copied = 0
        while True:
            rows = sc.fetchmany(_BATCH)
            if not rows:
                break
            dc.executemany(ins, rows)
            copied += len(rows)
        dst.commit()
        print(f"  {t}: {copied} rows 복사", flush=True)

    print("--- dev 최종 카운트 ---", flush=True)
    for t in _TABLES:
        dc.execute(f"SELECT COUNT(*) FROM {t}")
        print(f"  dev {t} = {dc.fetchone()[0]}", flush=True)
    sc.close(); dc.close(); src.close(); dst.close()
    print("===KB_COPY_DONE===", flush=True)


if __name__ == "__main__":
    main()
