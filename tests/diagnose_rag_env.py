"""
RAG 검증 환경 진단 — DB 연결 / KB 적재 / 임베딩 / hybrid_search 동작 확인.
민감 정보 출력 금지.
"""
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("diagnose")

print("="*70)
print("  RAG 환경 진단 시작")
print("="*70)

# 1) 환경변수 확인 (값 NEVER 출력, 존재 여부만)
print("\n[1] 환경변수 존재 여부")
env_vars = ["DATABASE_URL", "DB_PASSWORD", "DB_HOST", "DB_USER", "DB_NAME",
            "OPENAI_API_KEY", "RETRIEVAL_GATE_ENFORCE",
            "GATE_TOP1_PASS", "GATE_TOP1_WEAK", "GATE_CHUNK_COUNT_PASS",
            "GATE_TOPIC_MATCH_PASS", "GATE_WEIGHTED_PASS",
            "RAG_LLM_MODEL", "RAG_EMBEDDING_MODEL"]
for ev in env_vars:
    val = os.environ.get(ev, "")
    present = "SET" if val else "NOT SET"
    if ev in ("DATABASE_URL", "DB_PASSWORD", "OPENAI_API_KEY"):
        print(f"  {ev}: {present}")  # 값은 절대 출력 안 함
    else:
        # 가드레일 설정값은 안전하게 출력
        display = val[:40] if val and len(val) < 50 else ("SET" if val else "")
        print(f"  {ev}: {present}  (value={display})")

# 2) DB 연결 모드 확인
print("\n[2] DB 연결 모드")
from dbcommon import _use_postgres
print(f"  _use_postgres = {_use_postgres}")
if not _use_postgres:
    print("  WARNING: SQLite 모드입니다 — 운영 DB와 다릅니다!")

# 3) KB 데이터 확인
print("\n[3] KB 데이터 적재 현황")
try:
    from dbcommon import get_conn, _p, _ph

    with get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM kb_documents WHERE status='active'")
        row = cur.fetchone()
        doc_count = row[0] if isinstance(row, tuple) else list(row.values())[0]
        print(f"  active 문서: {doc_count}")

        cur.execute("SELECT COUNT(*) FROM kb_chunks")
        row = cur.fetchone()
        chunk_count = row[0] if isinstance(row, tuple) else list(row.values())[0]
        print(f"  총 청크: {chunk_count}")

        cur.execute("SELECT COUNT(*) FROM kb_chunks WHERE embedding_primary IS NOT NULL")
        row = cur.fetchone()
        embedded = row[0] if isinstance(row, tuple) else list(row.values())[0]
        print(f"  embedding_primary 적재: {embedded}")

        cur.execute("""
            SELECT d.source_id, COUNT(c.id) AS n
            FROM kb_documents d LEFT JOIN kb_chunks c ON c.document_id = d.id
            WHERE d.status='active' GROUP BY d.source_id ORDER BY d.source_id
        """)
        print(f"  source별 청크:")
        for row in cur.fetchall():
            sid = row[0] if isinstance(row, tuple) else row.get("source_id")
            n = row[1] if isinstance(row, tuple) else row.get("n")
            print(f"    {sid}: {n}")
except Exception as e:
    print(f"  KB 조회 실패: {e}")
    import traceback
    traceback.print_exc()

# 4) 임베딩 생성 테스트
print("\n[4] OpenAI 임베딩 생성 테스트")
try:
    from embedding_provider import get_embedding_provider
    provider = get_embedding_provider(slot="default")
    test_text = "성인 심정지 시 어떻게 해야 하나요?"
    emb = provider.embed_single(test_text)
    print(f"  임베딩 생성 성공: 차원={len(emb)}, 첫 5개 값={emb[:5]}")
except Exception as e:
    print(f"  임베딩 생성 실패: {e}")
    import traceback
    traceback.print_exc()

# 5) hybrid_search 직접 호출
print("\n[5] hybrid_search 직접 호출 테스트")
try:
    from rag_engine import hybrid_search
    test_queries = [
        ("성인 심정지 응급처치", ["nemc"]),
        ("당뇨병 관리", ["health_kdca"]),
        ("AED 사용법", ["nemc"]),
    ]
    for query, expected_source in test_queries:
        print(f"\n  Query: '{query}'")
        try:
            results = hybrid_search(query, top_k=10)
            print(f"  반환된 청크 수: {len(results)}")
            if results:
                top = results[0]
                src_id = top.get("source_id", "unknown")
                score = top.get("score", top.get("rrf_score", "N/A"))
                title = top.get("title", "")[:50]
                print(f"  Top1: source_id={src_id}, score={score}, title='{title}'")
            else:
                print(f"  결과 없음 (0건)")
        except Exception as e:
            print(f"  hybrid_search 오류: {e}")
            import traceback
            traceback.print_exc()
except Exception as e:
    print(f"  hybrid_search import 실패: {e}")

# 6) generate_response 시그니처 확인
print("\n[6] generate_response() 시그니처 확인")
try:
    import inspect
    from rag_engine import generate_response
    sig = inspect.signature(generate_response)
    print(f"  시그니처: {sig}")
except Exception as e:
    print(f"  시그니처 확인 실패: {e}")

print("\n" + "="*70)
print("  진단 완료")
print("="*70)
