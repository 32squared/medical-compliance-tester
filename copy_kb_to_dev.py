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


def _columns(cur, table):
    cur.execute(
        "SELECT column_name, udt_name FROM information_schema.columns "
        "WHERE table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    rows = cur.fetchall()
    cols = [r[0] for r in rows]
    vcols = {r[0] for r in rows if r[1] == "vector"}
    return cols, vcols


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

    for t in _TABLES:
        cols, vcols = _columns(dc, t)  # dev 스키마 기준 컬럼
        if not cols:
            print(f"  [skip] {t}: dev에 테이블/컬럼 없음", flush=True)
            continue
        sel = ", ".join((f"{c}::text" if c in vcols else c) for c in cols)
        ph = ", ".join((f"%s::vector" if c in vcols else "%s") for c in cols)
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
