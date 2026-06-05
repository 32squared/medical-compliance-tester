"""
verify_db_005.py — 단계 5 DB 검증 (배포 후 상태 확인)
Cloud Run Job 단일 실행용 — 결과를 stdout에 출력 후 종료
"""
import os
import sys
import urllib.parse

DB_HOST = os.environ.get("DB_HOST", "")
DB_USER = os.environ.get("DB_USER", "app_user")
DB_NAME = os.environ.get("DB_NAME", "medical_app")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")

if not DB_PASSWORD or not DB_HOST:
    print("[ERROR] DB_HOST / DB_PASSWORD 환경변수 미설정", file=sys.stderr)
    sys.exit(1)

DATABASE_URL = (
    f"postgresql://{DB_USER}:{urllib.parse.quote(DB_PASSWORD, safe='')}@/{DB_NAME}"
    f"?host={DB_HOST}"
)

try:
    import psycopg2
except ImportError:
    print("[ERROR] psycopg2 미설치", file=sys.stderr)
    sys.exit(1)

conn = psycopg2.connect(DATABASE_URL)
cur = conn.cursor()

print("=" * 60)
print("  [Q1] source_id별 문서 수 (active)")
print("=" * 60)
cur.execute("""
    SELECT source_id, COUNT(*) AS docs
    FROM kb_documents
    WHERE source_id IN ('nemc','health_kdca','consultation_seed','guideline_internal','gpt_generated_v1')
      AND status='active'
    GROUP BY source_id
    ORDER BY source_id
""")
for row in cur.fetchall():
    print(f"  source_id='{row[0]}'  docs={row[1]}")

print()
print("=" * 60)
print("  [Q2] 청크 총계 + 임베딩 완료 수")
print("=" * 60)
cur.execute("""
    SELECT COUNT(*) AS total_chunks, COUNT(embedding_primary) AS embedded
    FROM kb_chunks
""")
row = cur.fetchone()
print(f"  total_chunks={row[0]}  embedded={row[1]}")

print()
print("=" * 60)
print("  [Q3] health_kdca 최신 10건 (source_url 검증용)")
print("=" * 60)
cur.execute("""
    SELECT title, source_url, source_fetched_at
    FROM kb_documents
    WHERE source_id='health_kdca' AND status='active'
    ORDER BY created_at DESC LIMIT 10
""")
rows = cur.fetchall()
for i, row in enumerate(rows, 1):
    print(f"  [{i:02d}] title={row[0]}")
    print(f"       url={row[1]}")
    print(f"       fetched={row[2]}")

print()
print("=" * 60)
print("  [Q4] rag_queries Phase A 컬럼 확인")
print("=" * 60)
cur.execute("""
    SELECT column_name FROM information_schema.columns
    WHERE table_name='rag_queries'
      AND column_name IN ('evidence_quality','retrieval_top1_score','retrieval_chunk_count',
                          'retrieval_weighted_score','gate_decision','blocked_reasons',
                          'claims_json','verified_at')
    ORDER BY column_name
""")
cols = [r[0] for r in cur.fetchall()]
print(f"  rag_queries 신규 컬럼 ({len(cols)}개): {cols}")

cur.close()
conn.close()
print()
print("[DONE] DB 검증 완료")
