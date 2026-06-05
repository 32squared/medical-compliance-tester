"""RAG generate_response 직접 호출 진단 — Cloud Run Job용"""
import sys, io, json, traceback
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def main():
    print("=== RAG 디버깅 시작 ===", flush=True)

    # 1. DB 연결 검증
    print("\n[1] DB 연결 검증...", flush=True)
    try:
        import db
        db.init_db()
        if not db._use_postgres:
            print("ERROR: PostgreSQL 모드 아님. DATABASE_URL 확인.", flush=True)
            return
        # KB 청크 수 확인
        with db.get_conn() as (conn, cur):
            cur.execute("SELECT COUNT(*) FROM kb_chunks")
            chunk_count = cur.fetchone()["count"]
            cur.execute("SELECT COUNT(*) FROM kb_documents WHERE status='active'")
            doc_count = cur.fetchone()["count"]
        print(f"  kb_chunks: {chunk_count}, kb_documents(active): {doc_count}", flush=True)
    except Exception as e:
        print(f"DB ERROR: {e}", flush=True)
        traceback.print_exc()
        return

    # 2. 임베딩 프로바이더 검증
    print("\n[2] 임베딩 프로바이더 검증...", flush=True)
    try:
        from embedding_provider import get_embedding_provider
        emb = get_embedding_provider("default")
        hc = emb.health_check()
        print(f"  embedding_provider: {emb.model_id}, dim={emb.dimension}, health={hc}", flush=True)
    except Exception as e:
        print(f"EMBED ERROR: {e}", flush=True)
        traceback.print_exc()

    # 3. LLM 프로바이더 검증
    print("\n[3] LLM 프로바이더 검증...", flush=True)
    try:
        from llm_router import get_llm_provider
        llm = get_llm_provider()
        print(f"  llm_provider: {llm.provider_id} / model={llm.model_id}", flush=True)
    except Exception as e:
        print(f"LLM ERROR: {e}", flush=True)
        traceback.print_exc()

    # 4. hybrid_search 단독 호출 (왼쪽 팔 방사통)
    print("\n[4] hybrid_search 단독 호출...", flush=True)
    try:
        from rag_engine import hybrid_search
        results = hybrid_search("왼쪽 팔 방사통", top_k=5)
        print(f"  반환 청크 수: {len(results)}", flush=True)
        for i, r in enumerate(results[:5]):
            print(f"  [{i+1}] chunk_id={r.get('chunk_id')[:8] if r.get('chunk_id') else 'NULL'}, "
                  f"score={r.get('score', 0):.3f}, "
                  f"source={r.get('source_id')}, "
                  f"topic={r.get('evidence_topic')}, "
                  f"content_preview={(r.get('content') or '')[:80]}",
                  flush=True)
    except Exception as e:
        print(f"SEARCH ERROR: {e}", flush=True)
        traceback.print_exc()

    # 5. generate_response 전체 호출 (스트리밍)
    print("\n[5] generate_response 전체 호출...", flush=True)
    try:
        from rag_engine import generate_response
        full_text = ""
        event_count = 0
        for event in generate_response("왼쪽 팔 방사통", "debug-conv-001"):
            event_count += 1
            etype = event.get("type")
            if etype == "INFO":
                print(f"  [INFO] {json.dumps(event.get('data', {}), ensure_ascii=False)[:200]}", flush=True)
            elif etype == "GENERATION":
                txt = event.get("text", "")
                full_text += txt
                # 첫 5개 청크만 출력
                if event_count <= 10:
                    print(f"  [GEN #{event_count}] '{txt[:60]}'", flush=True)
            elif etype == "STOP":
                print(f"  [STOP] text_len={len(event.get('text',''))}", flush=True)
                print(f"  [STOP] citations={event.get('citations')}", flush=True)
                print(f"  [STOP] latency={event.get('latency_ms')}ms", flush=True)
                print(f"  [STOP] tokens={event.get('tokens')}", flush=True)
                print(f"  [STOP] guardrail_action={event.get('guardrail_action')}", flush=True)
                print(f"  [STOP] rag_query_id={event.get('rag_query_id')}", flush=True)
                # 전체 응답 텍스트 출력
                text = event.get("text", "")
                print(f"\n=== 최종 응답 텍스트 ({len(text)} chars) ===", flush=True)
                print(text[:2000], flush=True)
                if len(text) > 2000:
                    print(f"... [truncated, total {len(text)} chars]", flush=True)
            elif etype == "ERROR":
                print(f"  [ERROR] {event.get('message')}", flush=True)

        print(f"\n총 이벤트 수: {event_count}, 전체 텍스트 길이: {len(full_text)}", flush=True)

    except Exception as e:
        print(f"GENERATE ERROR: {e}", flush=True)
        traceback.print_exc()

    # 6. rag_queries 테이블 확인 (방금 INSERT된 행)
    print("\n[6] rag_queries 마지막 행 확인...", flush=True)
    try:
        with db.get_conn() as (conn, cur):
            cur.execute("""
                SELECT id, query_text, response_text, latency_total_ms,
                       guardrail_action, guardrail_violations,
                       token_input, token_output, created_at
                FROM rag_queries
                WHERE conversation_id='debug-conv-001'
                ORDER BY created_at DESC
                LIMIT 1
            """)
            row = cur.fetchone()
        if row:
            row = dict(row)
            print(f"  id={row['id']}", flush=True)
            print(f"  query={str(row['query_text'])[:60]}", flush=True)
            print(f"  response_len={len(row['response_text'] or '')}", flush=True)
            print(f"  response_preview={(row['response_text'] or '')[:300]}", flush=True)
            print(f"  latency={row['latency_total_ms']}ms", flush=True)
            print(f"  guardrail_action={row['guardrail_action']}", flush=True)
            print(f"  guardrail_violations={row['guardrail_violations']}", flush=True)
            print(f"  tokens={row['token_input']}+{row['token_output']}", flush=True)
        else:
            print("  rag_queries에 행 없음 — generate_response가 INSERT 실패", flush=True)
    except Exception as e:
        print(f"VERIFY ERROR: {e}", flush=True)
        traceback.print_exc()

    print("\n=== RAG 디버깅 끝 ===", flush=True)

if __name__ == "__main__":
    main()
