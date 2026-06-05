"""
copy_kb_to_dev.py — 운영 KB를 dev DB로 복제 (Dev RAG 테스트 셋팅용).

운영(SRC, 읽기전용) → dev(DST, 쓰기)로 kb_sources/kb_documents/kb_chunks를 복사한다.
운영 데이터를 그대로 복제하므로 재수집·재임베딩 없이 즉시 dev에서 RAG 인용 테스트 가능.

연결:
  SRC  = DATABASE_URL        (운영 medical_app, 읽기만)
  DST  = DST_DATABASE_URL    (dev medical_app_dev, 쓰기)
운영 잡의 DATABASE_URL은 그대로 두고 DST_DATABASE_URL만 추가하면 된다(repoint 아님).

특성:
- 멱등: ON CONFLICT DO NOTHING (이미 있는 행은 건너뜀)
- 벡터 컬럼(pgvector)은 ::text 로 읽고 ::vector 로 써서 임베딩 보존
- FK 순서 보장: sources → documents → chunks
"""

from __future__ import annotations

import os
import sys

import psycopg2

_TABLES = ["kb_sources", "kb_documents", "kb_chunks"]
_BATCH = 500
# 특수 타입: ::text 로 읽고 ::<udt> 로 써야 보존되는 컬럼 타입
_SPECIAL_UDT = {"vector", "tsvector"}

# kb_chunks DDL (db.py와 동일) — dev에 pgvector 확장 후 테이블이 없으면 생성
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


def _ensure_dev_schema(cur, conn):
    """dev에 pgvector 확장 + kb_chunks 테이블/인덱스 보장(없으면 생성)."""
    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    cur.execute(_KB_CHUNKS_DDL)
    for idx in _KB_CHUNKS_IDX:
        cur.execute(idx)
    conn.commit()
    print("  [dev schema] pgvector + kb_chunks 보장 완료", flush=True)


def _columns(cur, table):
    """반환: (cols, special) — special = {col: udt_name} (vector/tsvector)."""
    cur.execute(
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    rows = cur.fetchall()
    cols = [r[0] for r in rows]
    special = {r[0]: r[1] for r in rows if r[1] in _SPECIAL_UDT}
    return cols, special


def main():
    src_url = os.environ.get("DATABASE_URL")            # 운영(읽기)
    dst_url = os.environ.get("DST_DATABASE_URL")          # dev(쓰기)
    if not src_url or not dst_url:
        print("[copy_kb] ERROR: DATABASE_URL(운영) + DST_DATABASE_URL(dev) 둘 다 필요", flush=True)
        sys.exit(1)
    if "medical_app_dev" not in dst_url:
        print("[copy_kb] ERROR: 안전장치 — DST는 반드시 medical_app_dev 여야 함", flush=True)
        sys.exit(1)

    print("===KB_COPY_BEGIN===", flush=True)
    src = psycopg2.connect(src_url)
    dst = psycopg2.connect(dst_url)
    src.set_session(readonly=True)
    sc = src.cursor()
    dc = dst.cursor()

    _ensure_dev_schema(dc, dst)  # pgvector + kb_chunks 보장

    for t in _TABLES:
        cols, special = _columns(dc, t)  # dev 스키마 기준 컬럼 (special = {col: udt})
        if not cols:
            print(f"  [skip] {t}: dev에 테이블/컬럼 없음", flush=True)
            continue
        sel = ", ".join((f"{c}::text" if c in special else c) for c in cols)
        ph = ", ".join((f"%s::{special[c]}" if c in special else "%s") for c in cols)
        ins = (f"INSERT INTO {t} ({', '.join(cols)}) VALUES ({ph}) "
               f"ON CONFLICT DO NOTHING")
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
