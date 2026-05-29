# Evidence-first Medical RAG 스펙 준수 현황

> 기준 문서: `medical_rag_ai_build_master_prompt.md` + `medical_evidence_rag_build_work_order.md`
> 갱신: 2026-05-29 · 브랜치: `feature/rag-system`
> 범위: 그린필드 FastAPI 재작성이 아니라 **기존 RAG에 스펙 모듈을 통합**하는 방식.

---

## 모듈별 현황 (16개 + 부가)

| # | 스펙 모듈 | 이전 | **현재** | 구현물 |
|---|-----------|------|----------|--------|
| 1 | Source Registry | 🟡 | 🟢 | `kb_sources` + migration 009(priority_rank/jurisdiction/medical_domain) |
| 2 | Document/Chunk Store | 🟡 | 🟢 | `kb_chunks` + migration 009(source_priority/population_tags/risk_tags/recommendation_grade/chunk_type/heading_path) |
| 3 | Data Ingestion | 🟡 | 🟡 | kb_ingest + KDCA/MFDS/NEMC 수집. **DUR 구조데이터·PubMed·PMC 미흡(잔여)** |
| 4 | Question Classifier | ❌ | 🟢 | `medical_classifier.py` (LLM + 규칙 fallback), 테스트 10/10 |
| 5 | PHI/PII Masker + Consent | ❌ | 🟢 | `pii_masker.py` (정규식), 테스트 9/9. **consent 관리는 잔여** |
| 6 | Emergency/Red-flag Detector | 🟡 | 🟢 | classifier red_flags + analyzer + pipeline safety_first |
| 7 | Retrieval Router (intent→소스) | ❌ | 🟢 | `retrieval_router.py`, 테스트 포함 |
| 8 | Hybrid Retrieval | ✅ | ✅ | rag_engine RRF (기존) |
| 9 | Source Priority Reranker | 🟡 | 🟢 | retrieval_router.source_priority + evidence_pack 정렬 |
| 10 | Evidence Pack Builder | ❌ | 🟢 | `evidence_pack.py` (정식 JSON), 테스트 포함 |
| 11 | Grounded Answer Generator | ✅ | ✅ | rag_engine generate_response (기존) |
| 12 | Citation Verifier (claim-level) | 🟡 | 🟢 | `citation_verifier.py`, 테스트 9/9 |
| 13 | Medical Safety Post-filter | ✅ | ✅ | analyzer (기존, 오탐 수정 완료) |
| 14 | Audit Logger | 🟡 | 🟢 | rag_queries + migration 009(answer_id/model_version/prompt_version/classification_json/evidence_pack_json) + pipeline audit |
| 15 | Review Queue (고위험 답변) | ❌ | 🟢 | `review_queue.py` + review_queue_items 테이블, 테스트 6/6 |
| 16 | Evaluation Harness | ✅ | ✅ | batch_eval_rag + HealthBench 1100 + tests |
| ＋ | 파이프라인 오케스트레이션 | ❌ | 🟢 | `medical_rag_pipeline.py` (mask→classify→route→evidence→generate→verify→review→audit), e2e 7/7 |

🟢 구현/통합 · 🟡 부분 · ❌ 없음 · ✅ 기존 완비

**신규 모듈 단위 테스트: 53건 전부 통과** (PII 9 + 분류 10 + 라우터/근거 12 + 인용 9 + 검수 6 + 파이프라인 7).

---

## 진행 현황 업데이트 (2026-05-29)

### A. 라이브 통합 — ✅ 코드 완료 / ⏳ Cloud SQL 적용 대기
- `rag_engine.generate_response`에 **가드 배선 완료**(커밋): 진입부 PII 마스킹 + 규칙기반 분류,
  INSERT 후 감사필드(answer_id/model_version/prompt_version/classification_json) 갱신 + 고위험 답변 review_queue 적재.
- 모두 try/except 가드 → migration 009 미적용 상태에서도 **기존 96% 경로 무손상**(감사/검수는 009 적용 후 영구저장).
- `db.py`: add_review_item / update_rag_query_audit / list_review_queue 추가. 로컬 app.db 009 적용·검증 완료.
- `migrations/run_migration_009.py` runner 준비. **Cloud SQL 적용은 운영 DB 변경이라 사용자 승인 대기**(분류기 차단됨).
- ⏳ 잔여: ① migration 009 Cloud SQL 적용 ② (선택) 인용 `[N]`→`[E#]` Evidence Pack 형식 전환 — 전환 시 클라우드 재검증 필요.

### B. DUR 데이터 — ✅ 수집기 코드 완료 / ⏳ 실제 수집 대기
- `dur_collector.py`: 식약처 DUR OpenAPI 8종(병용/임부/연령/용량/투여기간/노인/효능군중복/서방정) 수집→kb_chunk 정규화. 단위 7/7.
- ⏳ 잔여: 실제 수집 실행(data.go.kr 키 `DATA_GO_KR_KEY` 필요) → KB ingest.
- PubMed/PMC OA 보조 수집기는 여전히 잔여.

### C. 정책/운영 (잔여)
- Consent(동의) 관리, retention 정책
- Review Console UI(검수자 라벨 입력)
- TTFT p95 4초 측정/튜닝 (현 SSE 스트리밍은 있음)

---

## 결론
- 스펙 16개 모듈 중 **핵심 안전/근거 모듈(분류·PII·라우터·Evidence Pack·Citation Verifier·Review Queue)을 구현·통합**했고, end-to-end 파이프라인으로 조립·테스트 완료.
- **라이브 배선 + DUR 데이터 + consent**가 주요 잔여 항목.
- 1100 평가(답변 품질 측정)는 이와 독립적으로 진행 가능.
