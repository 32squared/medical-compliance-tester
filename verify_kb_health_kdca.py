"""
verify_kb_health_kdca.py — health_kdca KB 적재 검증
DB 연결: DATABASE_URL 또는 DB_PASSWORD+DB_HOST 조합
"""
import os, sys, urllib.parse

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    _pw   = os.environ.get("DB_PASSWORD", "")
    _user = os.environ.get("DB_USER", "app_user")
    _name = os.environ.get("DB_NAME", "medical_app")
    _host = os.environ.get("DB_HOST", "")
    if _pw and _host:
        DATABASE_URL = (
            f"postgresql://{_user}:{urllib.parse.quote(_pw, safe='')}@/{_name}"
            f"?host={_host}"
        )

if not DATABASE_URL:
    print("[ERROR] DATABASE_URL 또는 DB_PASSWORD+DB_HOST 필요", file=sys.stderr)
    sys.exit(1)

import psycopg2
conn = psycopg2.connect(DATABASE_URL)
cur  = conn.cursor()

print("=" * 60)
print("  DB 검증 — health_kdca KB")
print("=" * 60)

# Q1: kb_sources
cur.execute("SELECT id, name FROM kb_sources WHERE id = 'health_kdca'")
row = cur.fetchone()
print(f"\n[Q1] kb_sources health_kdca: {row}")

# Q2: 문서 수 (nemc + health_kdca)
cur.execute("""
    SELECT source_id, COUNT(*) AS docs,
           SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) AS active
    FROM kb_documents
    WHERE source_id IN ('nemc','health_kdca')
    GROUP BY source_id
    ORDER BY source_id
""")
print("\n[Q2] 문서 수:")
for r in cur.fetchall():
    print(f"  source_id={r[0]!r}  docs={r[1]}  active={r[2]}")

# Q3: 청크 수
cur.execute("""
    SELECT d.source_id, COUNT(c.id) AS chunks
    FROM kb_documents d JOIN kb_chunks c ON c.document_id=d.id
    WHERE d.source_id IN ('nemc','health_kdca')
    GROUP BY d.source_id
    ORDER BY d.source_id
""")
print("\n[Q3] 청크 수:")
for r in cur.fetchall():
    print(f"  source_id={r[0]!r}  chunks={r[1]}")

# Q4: 임베딩 적재율
cur.execute("""
    SELECT COUNT(*) AS total, COUNT(embedding_primary) AS embedded
    FROM kb_chunks c
    JOIN kb_documents d ON d.id = c.document_id
    WHERE d.source_id = 'health_kdca'
""")
row = cur.fetchone()
print(f"\n[Q4] health_kdca 임베딩: total={row[0]}  embedded={row[1]}")

# Q5: 샘플 source_url
cur.execute("""
    SELECT title, source_url, source_fetched_at
    FROM kb_documents
    WHERE source_id = 'health_kdca'
    ORDER BY created_at DESC LIMIT 5
""")
print("\n[Q5] 샘플 문서 (최신 5건):")
rows = cur.fetchall()
if rows:
    for r in rows:
        print(f"  제목: {r[0]}")
        print(f"  URL:  {r[1]}")
        print(f"  수집: {r[2]}")
        print()
else:
    print("  (health_kdca 문서 없음)")

# Q6: 전체 KB active 문서/청크
cur.execute("""
    SELECT
        (SELECT COUNT(*) FROM kb_documents WHERE status='active') AS total_docs,
        (SELECT COUNT(*) FROM kb_chunks c JOIN kb_documents d ON d.id=c.document_id WHERE d.status='active') AS total_chunks
""")
row = cur.fetchone()
print(f"[Q6] 전체 KB active: docs={row[0]}  chunks={row[1]}")

cur.close()
conn.close()
print("\n" + "=" * 60)
print("  검증 완료")
print("=" * 60)
