"""
RAG KB 현황 감사 스크립트 — Cloud Run Job: kb-rag-audit
요청된 5개 SQL 항목을 실제 DB 스키마에 맞게 실행.
READ-ONLY (SELECT only, no modifications).

실제 스키마 기준:
  kb_sources: id, name, source_type, license, url, update_frequency, ...
  kb_documents: id, source_id, title, status, evidence_level, version, ...
               (evidence_country, regulatory_korea 없음 — kb_chunks에 있음)
  kb_chunks: embedding_primary, embedding_secondary (별도 컬럼)
             evidence_country, regulatory_korea, evidence_topic 있음
  rag 테이블: rag_queries (rag_responses 없음)
"""
import os
import sys
import io

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("[ERROR] psycopg2 not available")
    sys.exit(1)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')

# DB_PASSWORD secret이 주입된 경우 PLACEHOLDER를 실제 값으로 치환
if DB_PASSWORD and 'PLACEHOLDER' in DATABASE_URL:
    DATABASE_URL = DATABASE_URL.replace('PLACEHOLDER', DB_PASSWORD)

if not DATABASE_URL or 'PLACEHOLDER' in DATABASE_URL:
    print("[ERROR] DATABASE_URL 또는 DB_PASSWORD 환경변수가 설정되지 않았습니다.")
    sys.exit(1)


def connect():
    return psycopg2.connect(DATABASE_URL)


def run_query(conn, label, sql):
    print(f"\n{'='*60}")
    print(f"## {label}")
    print('='*60)
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
            if not rows:
                print("(결과 없음 — 테이블이 비어있거나 존재하지 않습니다)")
                return []
            cols = list(rows[0].keys())
            col_widths = {
                c: max(len(str(c)), max(
                    len(str(r[c])) if r[c] is not None else 4 for r in rows
                )) for c in cols
            }
            header = " | ".join(str(c).ljust(col_widths[c]) for c in cols)
            sep = "-+-".join("-" * col_widths[c] for c in cols)
            print(header)
            print(sep)
            for row in rows:
                line = " | ".join(
                    (str(row[c]) if row[c] is not None else "NULL").ljust(col_widths[c])
                    for c in cols
                )
                print(line)
            print(f"\n({len(rows)} rows)")
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[QUERY ERROR] {e}")
        return []


def main():
    print("RAG KB 현황 감사 조회 시작 (READ-ONLY)")
    print(f"DB: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else '(masked)'}")

    conn = connect()
    conn.autocommit = True

    # ── 1. 소스별 active/pending/deprecated 문서 수 ──
    # kb_sources에 category 없음 → source_type 대체 사용
    run_query(conn, "1. 소스별 status 분기 문서 수", """
SELECT
  s.id AS source_id,
  s.name AS source_name,
  s.source_type,
  COUNT(d.id) FILTER (WHERE d.status='active') AS active_docs,
  COUNT(d.id) FILTER (WHERE d.status='pending_review') AS pending_docs,
  COUNT(d.id) FILTER (WHERE d.status='deprecated') AS deprecated_docs,
  COUNT(d.id) AS total_docs
FROM kb_sources s
LEFT JOIN kb_documents d ON d.source_id = s.id
GROUP BY s.id, s.name, s.source_type
ORDER BY s.id
""")

    # ── 2. 청크 총계 (문서 status별) ──
    run_query(conn, "2. 청크 총계 (문서 status별)", """
SELECT
  d.status,
  COUNT(c.id) AS chunk_count,
  COUNT(DISTINCT d.id) AS doc_count
FROM kb_documents d
LEFT JOIN kb_chunks c ON c.document_id = d.id
GROUP BY d.status
ORDER BY d.status
""")

    # ── 3. 임베딩 적재율 ──
    # embedding 단일 컬럼 없음 → embedding_primary / embedding_secondary 별도 집계
    run_query(conn, "3. 임베딩 적재율 (primary / secondary)", """
SELECT
  COUNT(*) AS total_chunks,
  COUNT(embedding_primary) AS primary_embedded,
  COUNT(*) - COUNT(embedding_primary) AS primary_missing,
  COUNT(embedding_secondary) AS secondary_embedded,
  COUNT(*) - COUNT(embedding_secondary) AS secondary_missing
FROM kb_chunks
""")

    # ── 4a. 자문 메타 분포 — evidence_country (kb_chunks 기준) ──
    # kb_documents에 evidence_country 없음 → kb_chunks에서 집계
    run_query(conn, "4a. 자문 메타 분포 — evidence_country (kb_chunks, active 문서)", """
SELECT
  c.evidence_country,
  COUNT(*) AS chunk_count,
  COUNT(DISTINCT c.document_id) AS doc_count
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
WHERE d.status='active'
GROUP BY c.evidence_country
ORDER BY chunk_count DESC
""")

    # ── 4b. 자문 메타 분포 — evidence_level (kb_documents 기준) ──
    run_query(conn, "4b. 자문 메타 분포 — evidence_level (active 문서)", """
SELECT
  evidence_level,
  COUNT(*) AS doc_count
FROM kb_documents
WHERE status='active'
GROUP BY evidence_level
ORDER BY doc_count DESC
""")

    # ── 4c. 자문 메타 분포 — regulatory_korea (kb_chunks 기준) ──
    # kb_documents에 regulatory_korea 없음 → kb_chunks에서 집계
    run_query(conn, "4c. 자문 메타 분포 — regulatory_korea (kb_chunks, active 문서)", """
SELECT
  COUNT(*) FILTER (WHERE c.regulatory_korea=true) AS regulatory_korea_chunks,
  COUNT(*) FILTER (WHERE c.regulatory_korea=false OR c.regulatory_korea IS NULL) AS other_chunks,
  COUNT(DISTINCT c.document_id) AS total_docs
FROM kb_chunks c
JOIN kb_documents d ON d.id = c.document_id
WHERE d.status='active'
""")

    # ── 5. 최근 24시간 RAG 호출 통계 (rag_queries 테이블) ──
    # rag_responses 없음 → rag_queries 사용 (guardrail_action 컬럼)
    run_query(conn, "5. 최근 24시간 RAG 호출 통계 (rag_queries)", """
SELECT
  COUNT(*) AS total_calls,
  ROUND(AVG(latency_total_ms)::numeric, 1) AS avg_latency_ms,
  COUNT(*) FILTER (WHERE guardrail_action='pass') AS pass_count,
  COUNT(*) FILTER (WHERE guardrail_action='regenerated') AS regen_count,
  COUNT(*) FILTER (WHERE guardrail_action='blocked') AS blocked_count,
  COUNT(*) FILTER (WHERE guardrail_action='emergency_redirect') AS emergency_count
FROM rag_queries
WHERE created_at::timestamp > NOW() - INTERVAL '24 hours'
""")

    conn.close()
    print("\n" + "="*60)
    print("RAG KB 현황 감사 조회 완료")
    print("="*60)


if __name__ == '__main__':
    main()
