"""
KB 현황 통계 조회 스크립트 — Cloud Run Job: kb-stats
10개 SQL 쿼리를 순차 실행하고 결과를 stdout으로 출력.
"""
import os
import sys
import io
import json

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:
    print("[ERROR] psycopg2 not available")
    sys.exit(1)

DATABASE_URL = os.environ.get('DATABASE_URL', '')
if not DATABASE_URL:
    print("[ERROR] DATABASE_URL 환경변수가 설정되지 않았습니다.")
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
            # 헤더
            cols = list(rows[0].keys())
            col_widths = {c: max(len(str(c)), max(len(str(r[c])) if r[c] is not None else 4 for r in rows)) for c in cols}
            header = " | ".join(str(c).ljust(col_widths[c]) for c in cols)
            sep = "-+-".join("-" * col_widths[c] for c in cols)
            print(header)
            print(sep)
            for row in rows:
                line = " | ".join((str(row[c]) if row[c] is not None else "NULL").ljust(col_widths[c]) for c in cols)
                print(line)
            print(f"\n({len(rows)} rows)")
            return [dict(r) for r in rows]
    except Exception as e:
        print(f"[QUERY ERROR] {e}")
        return []


def main():
    print("KB 현황 통계 조회 시작")
    print(f"DB: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL}")

    conn = connect()
    conn.autocommit = True

    # ── 1. 소스별 개요 ──
    run_query(conn, "1. 소스별 개요", """
SELECT
  s.id, s.name, s.source_type, s.license, s.update_frequency,
  COUNT(DISTINCT d.id) AS doc_count,
  COUNT(c.id) AS chunk_count,
  ROUND(AVG(c.token_count)::numeric, 1) AS avg_tokens_per_chunk,
  MIN(d.created_at)::date AS first_added,
  MAX(d.updated_at)::date AS last_updated
FROM kb_sources s
LEFT JOIN kb_documents d ON d.source_id = s.id AND d.status='active'
LEFT JOIN kb_chunks c ON c.document_id = d.id
GROUP BY s.id, s.name, s.source_type, s.license, s.update_frequency
ORDER BY chunk_count DESC
""")

    # ── 2. 상태별 문서 수 ──
    run_query(conn, "2. 상태별 문서 수", """
SELECT status, COUNT(*) FROM kb_documents GROUP BY status ORDER BY COUNT(*) DESC
""")

    # ── 3. evidence_level 분포 ──
    run_query(conn, "3. evidence_level (근거 수준) 분포", """
SELECT evidence_level, COUNT(*) AS docs
FROM kb_documents WHERE status='active'
GROUP BY evidence_level ORDER BY evidence_level
""")

    # ── 4. 자문 반영 메타 필드 분포 ──
    run_query(conn, "4. 자문 반영 메타 필드 분포", """
SELECT
  COUNT(*) FILTER (WHERE evidence_country='KR') AS kr_chunks,
  COUNT(*) FILTER (WHERE evidence_country!='KR' AND evidence_country IS NOT NULL) AS non_kr_chunks,
  COUNT(*) FILTER (WHERE regulatory_korea=true) AS regulatory_kr_chunks,
  COUNT(DISTINCT evidence_topic) AS unique_topics,
  COUNT(*) FILTER (WHERE evidence_topic IS NULL OR evidence_topic='') AS missing_topic
FROM kb_chunks
""")

    # ── 5. evidence_topic 분포 (상위 20) ──
    run_query(conn, "5. evidence_topic 분포 (상위 20)", """
SELECT evidence_topic, COUNT(*) AS chunk_count
FROM kb_chunks WHERE evidence_topic IS NOT NULL AND evidence_topic != ''
GROUP BY evidence_topic ORDER BY chunk_count DESC LIMIT 20
""")

    # ── 6. consultation_seed 증상별 청크 수 ──
    run_query(conn, "6. consultation_seed 증상(symptom_key) 청크 분포", """
SELECT d.title, COUNT(c.id) AS chunks
FROM kb_documents d
LEFT JOIN kb_chunks c ON c.document_id = d.id
WHERE d.source_id='consultation_seed' AND d.status='active'
GROUP BY d.id, d.title
ORDER BY d.title
""")

    # ── 7. guideline_internal 항목 ──
    run_query(conn, "7. guideline_internal 항목", """
SELECT d.title, COUNT(c.id) AS chunks
FROM kb_documents d
LEFT JOIN kb_chunks c ON c.document_id = d.id
WHERE d.source_id='guideline_internal' AND d.status='active'
GROUP BY d.id, d.title
ORDER BY d.title
""")

    # ── 8. 청크 길이 분포 ──
    run_query(conn, "8. 청크 길이 분포", """
SELECT
  ROUND(MIN(token_count)) AS min_tokens,
  ROUND(AVG(token_count)::numeric, 1) AS avg_tokens,
  ROUND(MAX(token_count)) AS max_tokens,
  PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY token_count) AS median_tokens
FROM kb_chunks
""")

    # ── 9. severity 분포 ──
    run_query(conn, "9. severity 분포", """
SELECT severity, COUNT(*) FROM kb_chunks
WHERE severity IS NOT NULL AND severity != ''
GROUP BY severity ORDER BY COUNT(*) DESC
""")

    # ── 10. 최근 24시간 RAG 호출 통계 ──
    run_query(conn, "10. 최근 24시간 RAG 호출 통계", """
SELECT
  COUNT(*) AS total_queries,
  COUNT(*) FILTER (WHERE guardrail_action='pass') AS passed,
  COUNT(*) FILTER (WHERE guardrail_action='blocked') AS blocked,
  COUNT(*) FILTER (WHERE guardrail_action='regenerated') AS regenerated,
  COUNT(*) FILTER (WHERE guardrail_action='emergency_redirect') AS emergency,
  ROUND(AVG(latency_total_ms)::numeric / 1000, 2) AS avg_latency_sec,
  ROUND(AVG(token_input)::numeric, 0) AS avg_input_tokens,
  ROUND(AVG(token_output)::numeric, 0) AS avg_output_tokens
FROM rag_queries
WHERE created_at > to_char(NOW() - INTERVAL '24 hours', 'YYYY-MM-DD"T"HH24:MI:SS')
""")

    conn.close()
    print("\n" + "="*60)
    print("KB 현황 통계 조회 완료")
    print("="*60)


if __name__ == '__main__':
    main()
