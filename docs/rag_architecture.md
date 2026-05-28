# 자체 RAG 시스템 도입 기획서

**프로젝트**: medical-compliance-tester → 자체 RAG 응답 생성기 추가
**작성일**: 2026-05-27
**작성자**: 기획/아키텍트 (Claude)
**버전**: v0.1 (검토용 초안)

---

## 1. 목표 & 비목표

### 1.1 목표 (Goals)

| # | 목표 | 측정 지표 |
|---|------|----------|
| G1 | **의료법 준수 우위** 확보 — SKIX 대비 Composite Reward 평균 +0.10 이상 | 동일 시나리오 100개 배치에서 RAG 평균 reward > SKIX 평균 reward |
| G2 | **출처 추적성(Citation)** — 모든 응답에 인용 출처 1개 이상 포함, KB 청크 ID까지 역추적 | citation_rate ≥ 95%, rag_queries 테이블에서 chunk_id → kb_chunks JOIN 가능 |
| G3 | **다중 LLM 비교** — 라우터로 OpenAI/Claude/Vertex/자체호스팅 무중단 전환 | settings.html에서 드롭다운으로 변경 후 즉시 반영, 동일 KB로 모델별 응답 비교 |
| G4 | **SKIX 병렬 운영(A/B)** — 같은 시나리오 양쪽 호출 → 평가 시스템 재사용 → 우열 자동 판정 | history.html에 side-by-side 비교 뷰, Arena 인프라 재사용 |
| G5 | **데이터 소유권** — 모든 KB·질의·응답이 자체 PostgreSQL에 저장. 외부 의존 단일 = LLM API뿐 | kb_chunks 행 수 ≥ 5,000 (Phase 1 종료 시점), 외부 검색 의존 없음 |

### 1.2 비목표 (Non-Goals) — 이번 작업에서 **하지 않음**

- **PROD 진단·처방 기능 제공**: 어디까지나 *테스트 도구 내부의 응답 생성기*. 환자에게 직접 노출 안 함.
- **자체 임베딩 모델 학습**: 사전학습된 모델만 사용 (BGE-M3 / OpenAI / KoSimCSE).
- **자체 LLM 학습/파인튜닝**: RLHF 데이터셋은 export만 (이미 `preference_pairs` 존재). 실제 학습은 별도 파이프라인.
- **SKIX 제거**: 병렬 운영. SKIX 코드는 그대로 유지.
- **실시간 KB 자동 크롤링**: 수동/배치 ingest만. 크롤러는 Phase 5+.
- **다국어 지원**: 한국어 KB만.
- **이미지/PDF OCR**: 텍스트 ingest만 지원. PDF는 외부 도구로 변환 후 업로드.

---

## 2. 시스템 아키텍처

### 2.1 컴포넌트 다이어그램

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          chat_tester.html                                │
│   [엔드포인트 토글] ⊙ SKIX  ⊙ RAG  ⊙ Both(A/B)                          │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ POST (SSE)
                                 ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                      proxy_server.py (라우팅 계층)                       │
│                                                                          │
│   POST /                  ─→ _proxy_post()           [SKIX 기존]        │
│   POST /api/rag/chat      ─→ _rag_chat()             [신규]              │
│   POST /api/rag/kb/*      ─→ _kb_admin()             [신규]              │
└────────────┬──────────────────────────────┬─────────────────────────────┘
             │                              │
             ▼                              ▼
   ┌─────────────────┐         ┌────────────────────────────────────┐
   │  SKIX(케이론)   │         │     rag_engine.py (신규 모듈)       │
   │  외부 API       │         │                                    │
   └─────────────────┘         │  ┌─────────────────────────────┐  │
                               │  │ (a) Retriever                │  │
                               │  │   - pgvector cosine          │  │
                               │  │   - tsvector BM25            │  │
                               │  │   - Hybrid (RRF)             │  │
                               │  │   - red_flag boost           │  │
                               │  └────────────┬─────────────────┘  │
                               │               ▼                    │
                               │  ┌─────────────────────────────┐  │
                               │  │ (b) Re-ranker                │  │
                               │  │   - cross-encoder OR         │  │
                               │  │   - LLM-as-reranker          │  │
                               │  └────────────┬─────────────────┘  │
                               │               ▼                    │
                               │  ┌─────────────────────────────┐  │
                               │  │ (c) Prompt Builder           │  │
                               │  │   ← guidelines.json          │  │
                               │  │   ← fixed_notices            │  │
                               │  │   ← consultation_checklists  │  │
                               │  │     (symptom 매칭)           │  │
                               │  └────────────┬─────────────────┘  │
                               │               ▼                    │
                               │  ┌─────────────────────────────┐  │
                               │  │ (d) LLM Router               │  │
                               │  │   provider: openai | anthro  │  │
                               │  │            | vertex | self   │  │
                               │  │   → SSE 스트리밍 정규화      │  │
                               │  └────────────┬─────────────────┘  │
                               │               ▼                    │
                               │  ┌─────────────────────────────┐  │
                               │  │ (e) Guardrails (post-gen)    │  │
                               │  │   - analyzer.py 정규식 검사  │  │
                               │  │   - 위반 시 차단/재생성      │  │
                               │  │   - 인용 강제 검증           │  │
                               │  └────────────┬─────────────────┘  │
                               │               ▼                    │
                               │  ┌─────────────────────────────┐  │
                               │  │ (f) Response Synthesizer     │  │
                               │  │   - SSE 포맷 (SKIX 호환)     │  │
                               │  │   - search_results = chunks  │  │
                               │  └─────────────────────────────┘  │
                               └────────────────┬───────────────────┘
                                                ▼
                               ┌─────────────────────────────────────┐
                               │   PostgreSQL (Cloud SQL + pgvector) │
                               │   kb_documents / kb_chunks (vec)    │
                               │   kb_sources / rag_queries          │
                               │   llm_providers                     │
                               └─────────────────────────────────────┘
```

### 2.2 SKIX 경로와의 분기점

- **기존**: `chat_tester.html` → `fetch(proxyUrl, { headers: { 'X-Target-URL': targetUrl } })` → `proxy_server.py do_POST` → fallthrough `self._proxy_post(body)` (line 4226)
- **신규 분기**: 클라이언트 측 `endpointMode` 변수가 `'rag'` 또는 `'both'`이면 fetch URL을 `/api/rag/chat`으로 변경. `'both'`는 두 번 호출 (병렬 `Promise.all`).
- 서버 측 분기는 **path 기반**으로만 결정 (헤더로 분기하지 않음 → 기존 SKIX 경로 무손상).

### 2.3 데이터 흐름 (사용자 질의 한 건 기준)

```
사용자 입력
    │
    ▼
[1] /api/rag/chat 도착 → 인증 체크 → tester_id 추출
    │
    ▼
[2] 질의 임베딩 (1회, ~150ms) — 임베딩 모델 호출
    │
    ▼
[3] Hybrid Search (병렬):
       ├ pgvector top-20 (cosine)
       └ tsvector top-20 (BM25 ts_rank)
    │
    ▼ Reciprocal Rank Fusion (RRF, k=60)
    │
    ▼
[4] consultation_checklists 매칭 → 증상 키워드 검출 → 해당 red_flags 키워드 가진 청크 +30% boost
    │
    ▼
[5] Re-ranker로 상위 5개 추림 (옵션, Phase 2부터)
    │
    ▼
[6] 프롬프트 조립:
       system = guideline_loader.build_gpt_system_prompt() + RAG 지침
       user   = 컨텍스트(인용 번호 [1][2]..) + 질문
    │
    ▼
[7] LLM 라우터 → SSE 스트리밍 시작
    │
    ▼ (스트리밍 중)
    │
[8] 토큰 누적 → 응답 완성 후 즉시
       ├ analyzer.py 정규식 검사 (가드레일)
       └ 인용 번호 검증 ([1], [2] 등 패턴 매칭)
    │
    ▼
[9] 위반 시:
       - CRITICAL: 차단 + 안전 응답 대체
       - HIGH: 재생성 1회 (system 프롬프트에 위반 경고 추가)
    │
    ▼
[10] 최종 응답 → 클라이언트 SSE 전달 + rag_queries 저장
       (response, retrieved_chunk_ids, llm_provider, latency, violations)
    │
    ▼
[11] 클라이언트 측에서 기존 평가 API 호출 (변경 없음)
        /api/evaluate, /api/evaluate-consultation
```

---

## 3. 지식 베이스 설계

### 3.1 3개 소스 비교표

| 항목 | 공개 의료 가이드라인 | 공공기관 데이터 | 자체 작성 콘텐츠 |
|------|---------------------|----------------|------------------|
| **출처** | 대한의학회 KMLE, PubMed 요약, UpToDate Patient | HIRA(심평원), KDCA(질병관리청), MFDS(식약처) | 병원·클리닉 의사 직접 작성 |
| **수집 방식** | 수동 다운로드 → 변환 → 업로드 | OpenAPI / CSV / Excel 다운로드 → 파싱 | UI 입력 또는 마크다운 업로드 |
| **라이선스** | PubMed: 대부분 public domain, 일부 CC. KMLE: 라이선스 검토 필요 | 공공누리(KOGL): 출처 표시 시 자유 | 자체 소유 (병원과 계약) |
| **업데이트 주기** | 분기 1회 (수동) | 월 1회 (자동 스크립트) | 의사 작성 시 즉시 (승인 후) |
| **신뢰도(evidence_level)** | A (높음) | B (중간 — 통계·역학) | A (도메인 전문가) |
| **승인 필요?** | 아니오 (외부 권위) | 아니오 | **예 (의사 reviewer 승인 필수)** |
| **MVP 초기 수량 목표** | 500 문서 | 200 문서 | 100 문서 (병원 시드) |

### 3.2 청킹 전략

의료 문서는 **증상 → 감별진단 → 처치 흐름**을 유지해야 하므로 일반 `RecursiveCharacterTextSplitter` 그대로는 위험.

```
청킹 알고리즘:
  1. 마크다운/HTML 헤더(#, ##, <h1>~<h3>) 기준 1차 분할 → "섹션"
  2. 섹션 단위로 토큰 측정:
       - 512 토큰 이하: 그대로 1개 청크
       - 512~1024: 그대로 1개 청크 (overflow 허용, 의미 유지 우선)
       - 1024 초과: 문장 단위로 2차 분할 (KoNLPy 형태소 기반 문장 경계)
  3. 앞뒤 청크 50토큰 overlap (헤더 컨텍스트 유지)
  4. 각 청크에 부모 섹션 제목을 메타데이터로 부착 (검색 결과 표시용)
  5. 표(table)는 마크다운 표 형식 유지 — 청크 중간에서 절대 자르지 않음
```

### 3.3 임베딩 모델 후보

| 모델 | 차원 | 한국어 | 의료 도메인 | 비용 | 호스팅 | 평가 |
|------|------|--------|------------|------|--------|------|
| **BGE-M3** (BAAI) | 1024 | 우수 | 일반 | 무료 (자체호스팅) | GPU 필요 | **MVP 권장** — 멀티벡터(dense+sparse+colbert) 지원 |
| OpenAI text-embedding-3-large | 3072 | 양호 | 일반 | $0.13/1M tok | API | Phase 2 비교군 |
| KoSimCSE-bert | 768 | 한국어 특화 | 일반 | 무료 | CPU 가능 | 경량 fallback |
| MedCPT (NCBI) | 768 | 영어만 | 의료 특화 | 무료 | GPU | 영문 PubMed 청크용 (옵션) |

**MVP 결정 (확정)**: **OpenAI text-embedding-3-small (1536차원) 단독 운영**으로 빠르게 시작 → 안정화 후 BGE-M3로 단계별 마이그레이션.

- MVP 시작 시 인프라 부담 최소 (API 키만 있으면 끝)
- Phase 1부터 `embedding_provider.py` 추상화 + `kb_chunks` 듀얼 컬럼(primary/secondary) 미리 구축 → 나중에 BGE-M3로 갈아탈 때 코드·DB 변경 최소화
- 전환은 사용자 승인 체크포인트 7단계로 통제 (자동 전환 절대 없음)
- 상세 마이그레이션 절차: [embedding_migration_strategy.md](./embedding_migration_strategy.md)

### 3.4 메타데이터 스키마

```jsonc
{
  "chunk_id": "uuid",
  "document_id": "uuid",
  "source_id": "kmle|hira|hospital_seoul|...",
  "source_type": "guideline|public|internal",
  "license": "public_domain|kogl_type1|proprietary",
  "title": "발열 환자 평가",
  "section_path": ["내과", "감염질환", "발열"],
  "content": "...",
  "evidence_level": "A|B|C",        // A=가이드라인, B=공공통계, C=전문가의견
  "symptom_tags": ["fever", "infection"],  // consultation_checklists의 symptom_key와 매칭
  "age_group": ["adult", "child", "elderly"],
  "severity": "mild|moderate|severe|emergency",
  "department": "내과",
  "language": "ko",
  "author_md_id": "user_id (자체 콘텐츠만)",
  "approved_by": "reviewer_user_id (자체 콘텐츠만)",
  "approved_at": "iso datetime",
  "last_verified_date": "iso date",  // 의료 정보 신선도
  "url": "원본 URL (있으면)",
  "embedding": "vector(1024)",

  // === 자문 결과 반영 신규 필드 (2026-05-27, expert_review_insights.md) ===
  "evidence_country": "KR",            // KR / US / EU / other — 한국 의료환경 자료만 검색 부스팅 (양현종 자문 반영)
  "evidence_topic": "fever_pediatric", // 문서가 다루는 핵심 주제 — 임베딩 + 주제 일치 검증 (양현종: 참고문헌이 주제와 무관한 사례 발견)
  "regulatory_korea": true,             // 심평원·식약처 기준 관련 여부 — 항생제 처방 제한 같은 국내 규제 매칭
  "topic_keywords": ["발열", "소아", "원인검사"]  // BM25 보조 + 주제 일치 검증용
}
```

**자문 반영 핵심**: `evidence_topic`과 `topic_keywords`는 **양현종(소청과) 자문 결과 직접 반영**. 소아 발열 시나리오에서 참고문헌이 (아토피·movement disorder·항말라리아제)로 완전 무관했던 문제를 방지. 검색 시 retrieved chunk의 `evidence_topic`이 질의 주제와 일치하는지 자동 검증.

### 3.5 의사 승인 워크플로 (자체 콘텐츠 소스 전용)

```
[draft]                  [pending_review]            [approved]            [active]
  │ 의사 작성              │ reviewer에게 배정          │ 의사 reviewer 승인  │ 검색 노출
  │ 또는 마크다운 업로드   │ (manage_kb 권한)           │                     │
  └──→ kb_documents.status: draft → pending_review → approved → active
                                                          │
                                                          ▼
                                                    [임베딩 자동 실행]
                                                    [kb_chunks INSERT]
                                                          │
                                                          ▼
                                                    [reject] ←─ 거부 사유 기록
```

- 신규 권한 코드 추가: `manage_kb` (의사 reviewer)
- `kb_documents.status`로 라이프사이클 관리, active 외 상태는 검색에서 제외

---

## 4. DB 스키마 추가안

기존 PostgreSQL + pgvector extension.

**SQLite 듀얼 모드 처리 정책 (확정, 2026-05-27)**:
- 기존 프로젝트의 PostgreSQL(prod) / SQLite(로컬 개발) 듀얼 구조는 **유지**.
- RAG는 **pgvector 의존** → SQLite 모드에서는 `/api/rag/*` 모든 라우트가 **HTTP 503** 반환 + 명확한 에러 메시지 (`"RAG features require PostgreSQL with pgvector. Set DATABASE_URL to enable."`)
- 로컬에서 RAG를 테스트하려면: (a) Cloud SQL 프록시 사용, (b) Docker로 로컬 PostgreSQL+pgvector 실행, (c) `RAG_MOCK=true` 환경변수로 mock 응답 (프론트엔드 개발용)
- 기존 SKIX 경로·인증·시나리오·평가 등 **다른 모든 기능은 SQLite에서 그대로 동작** (기존 듀얼 구조 무손상)

### 4.1 신규 테이블 (6개)

```sql
-- 1. KB 소스 정보
CREATE TABLE kb_sources (
    id TEXT PRIMARY KEY,                    -- 'kmle' / 'hira' / 'hospital_seoul'
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,              -- 'guideline' | 'public' | 'internal'
    license TEXT NOT NULL,                  -- 'public_domain' | 'kogl_type1' | 'proprietary'
    url TEXT,
    update_frequency TEXT,                  -- 'monthly' | 'quarterly' | 'on_demand'
    last_updated_at TEXT,
    is_active INTEGER DEFAULT 1,
    created_at TEXT NOT NULL
);

-- 2. KB 문서 원본
CREATE TABLE kb_documents (
    id TEXT PRIMARY KEY,                    -- uuid
    source_id TEXT REFERENCES kb_sources(id),
    title TEXT NOT NULL,
    content_md TEXT NOT NULL,               -- 원본 마크다운
    metadata_json TEXT DEFAULT '{}',        -- symptom_tags, age_group 등
    status TEXT DEFAULT 'draft',            -- draft|pending_review|approved|active|archived
    author_id TEXT,                         -- 작성자 (자체 콘텐츠)
    approved_by TEXT,                       -- 승인자
    approved_at TEXT,
    rejected_reason TEXT,
    evidence_level CHAR(1) DEFAULT 'B',     -- 'A' | 'B' | 'C'
    last_verified_date TEXT,
    version INTEGER DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX idx_kb_documents_status ON kb_documents(status);
CREATE INDEX idx_kb_documents_source ON kb_documents(source_id);

-- 3. KB 청크 + 벡터
CREATE EXTENSION IF NOT EXISTS vector;  -- pgvector
CREATE EXTENSION IF NOT EXISTS pg_trgm; -- BM25 보조

CREATE TABLE kb_chunks (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    section_path TEXT,                      -- JSON array of section titles
    -- 임베딩 듀얼 컬럼 (마이그레이션 대비, embedding_migration_strategy.md 참조)
    embedding_primary vector(1536),         -- 활성 모델 (Phase 1: OpenAI text-embedding-3-small)
    embedding_secondary vector(1024),       -- 보조 모델 (Phase 4: BGE-M3, 듀얼 인덱싱 동안 채워짐)
    embedding_primary_model TEXT NOT NULL,  -- 'openai_small_v3' / 'bge_m3'
    embedding_secondary_model TEXT,         -- NULL이면 듀얼 모드 아님
    secondary_indexed_at TEXT,              -- 보조 임베딩 생성 시점
    token_count INTEGER,
    symptom_tags TEXT DEFAULT '[]',         -- JSON array
    severity TEXT,
    content_tsv tsvector,                   -- BM25용
    created_at TEXT NOT NULL
);
-- 벡터 인덱스: primary/secondary 각각 — pgvector 0.5+ HNSW
CREATE INDEX idx_kb_chunks_emb_primary ON kb_chunks
    USING hnsw (embedding_primary vector_cosine_ops) WITH (m = 16, ef_construction = 64);
-- secondary는 듀얼 인덱싱 진행 시점에 생성 (마이그레이션 단계 3에서):
-- CREATE INDEX idx_kb_chunks_emb_secondary ON kb_chunks
--     USING hnsw (embedding_secondary vector_cosine_ops) WITH (m = 16, ef_construction = 64);
-- BM25 인덱스
CREATE INDEX idx_kb_chunks_tsv ON kb_chunks USING gin(content_tsv);
-- 메타 필터링용
CREATE INDEX idx_kb_chunks_document ON kb_chunks(document_id);

-- 4. LLM 프로바이더 설정
CREATE TABLE llm_providers (
    id TEXT PRIMARY KEY,                    -- 'openai_gpt4o' / 'anthropic_sonnet' 등
    label TEXT NOT NULL,
    provider TEXT NOT NULL,                 -- 'openai' | 'anthropic' | 'vertex' | 'self_hosted'
    model_id TEXT NOT NULL,                 -- 'gpt-4o' / 'claude-opus-4' 등
    base_url TEXT,                          -- self_hosted 용
    api_key_encrypted TEXT,                 -- 마스킹 방어
    max_tokens INTEGER DEFAULT 2048,
    temperature REAL DEFAULT 0.3,
    streaming_supported INTEGER DEFAULT 1,
    is_active INTEGER DEFAULT 1,
    cost_per_1m_input REAL,                 -- $ 추적
    cost_per_1m_output REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 5. RAG 질의 로그 (감사 추적)
CREATE TABLE rag_queries (
    id TEXT PRIMARY KEY,
    conversation_id TEXT,
    user_id TEXT,
    query_text TEXT NOT NULL,
    query_embedding vector(1024),           -- 디버깅용, 옵션
    retrieved_chunk_ids TEXT NOT NULL,      -- JSON array
    rerank_scores TEXT,                     -- JSON [{chunk_id, score}]
    llm_provider_id TEXT,
    system_prompt_hash TEXT,                -- 어떤 프롬프트 썼는지 추적
    response_text TEXT,
    citations_json TEXT,                    -- 인용 매핑 [{marker:"[1]", chunk_id:"..."}]
    latency_total_ms INTEGER,
    latency_retrieval_ms INTEGER,
    latency_llm_ms INTEGER,
    token_input INTEGER,
    token_output INTEGER,
    cost_usd REAL,
    guardrail_violations TEXT,              -- JSON array
    guardrail_action TEXT,                  -- 'pass' | 'regenerated' | 'blocked'
    created_at TEXT NOT NULL
);
CREATE INDEX idx_rag_queries_conv ON rag_queries(conversation_id);
CREATE INDEX idx_rag_queries_user ON rag_queries(user_id);
CREATE INDEX idx_rag_queries_date ON rag_queries(created_at);

-- 6. (선택) 의사 KB 피드백 — response_feedback과 별도
CREATE TABLE kb_feedback (
    id TEXT PRIMARY KEY,
    rag_query_id TEXT REFERENCES rag_queries(id),
    chunk_id TEXT REFERENCES kb_chunks(id),
    feedback_type TEXT,                     -- 'good_citation' | 'irrelevant' | 'outdated' | 'wrong_info'
    note TEXT,
    evaluator_id TEXT,
    created_at TEXT NOT NULL
);
```

### 4.2 기존 테이블 활용 (변경 없음)

- `response_feedback`: RAG 응답에도 동일하게 사용 (message_id 기반).
- `preference_pairs`: SKIX vs RAG 비교에서 winner를 chosen으로 자동 생성 가능.
- `arena_model_configs`: RAG 엔드포인트도 slot으로 등록 가능. **이미 인프라가 있음** — `endpoint_url`을 `/api/rag/chat`으로, `graph_type`을 `RAG`로 두면 재사용.
- `test_runs`: 배치 결과는 그대로. `results` JSON 안에 `rag_query_id` 추가만 하면 감사 추적 가능.

### 4.3 인덱스 권고 (수십만 청크 시)

| 청크 수 | 인덱스 | ef_search | 추정 latency |
|---------|--------|-----------|--------------|
| <10K | brute force (인덱스 불필요) | - | 50ms |
| 10K~100K | HNSW (m=16) | 40 | 30~80ms |
| 100K~1M | HNSW (m=24, ef_const=128) | 80 | 50~150ms |
| >1M | IVFFlat (lists=√N) + 분할 | - | 100~300ms |

→ MVP는 HNSW(m=16) 시작. 청크 50K 돌파 시 ef_construction 재빌드.

---

## 5. RAG 검색 & 합성 파이프라인

### 5.1 하이브리드 검색 (RRF 방식)

```python
# rag_engine.py (의사코드)
def hybrid_search(query, top_k=20, alpha=0.5):
    # 1. Dense (pgvector cosine)
    q_emb = embed(query)
    dense_results = SELECT id, 1 - (embedding <=> q_emb) AS score
                    FROM kb_chunks
                    JOIN kb_documents ON ...
                    WHERE kb_documents.status = 'active'
                    ORDER BY embedding <=> q_emb
                    LIMIT 20

    # 2. Sparse (tsvector BM25)
    sparse_results = SELECT id, ts_rank(content_tsv, to_tsquery('korean', $1)) AS score
                     FROM kb_chunks ...
                     ORDER BY score DESC
                     LIMIT 20

    # 3. RRF (Reciprocal Rank Fusion, k=60)
    scores = {}
    for rank, r in enumerate(dense_results):
        scores[r.id] = scores.get(r.id, 0) + 1.0 / (60 + rank)
    for rank, r in enumerate(sparse_results):
        scores[r.id] = scores.get(r.id, 0) + 1.0 / (60 + rank)
    return sorted(scores, key=scores.get, reverse=True)[:top_k]
```

### 5.2 의료 가드: red_flag boost (기존 자산 재활용)

```
1. 질의에서 증상 키워드 검출 → consultation_checklists.json의 symptom_key 매칭
   예: "열이 나요" → symptom_key="fever"
2. 해당 체크리스트의 red_flags 키워드를 청크 content에서 찾기
   예: fever의 red_flags = ["고열", "의식 변화", "호흡곤란"]
3. red_flag 키워드 포함 청크는 RRF 점수 × 1.3 boost
4. severity="emergency" 메타데이터 청크는 추가 × 1.2 boost
```

→ 응급 정보 누락 방지. 기존 `consultation_checklists.json`을 **검색 단계에서도** 재사용한다는 점이 핵심.

### 5.3 재랭킹 트레이드오프

| 방식 | 정확도 | 지연 | 비용 | Phase |
|------|--------|------|------|-------|
| RRF만 (재랭킹 없음) | 70% | +0ms | $0 | Phase 1 MVP |
| Cross-encoder (bge-reranker-v2-m3) | 85% | +200ms | GPU 호스팅비 | Phase 2 |
| LLM-as-reranker (gpt-4o-mini) | 88% | +1500ms | $0.0001/query | Phase 2 옵션 |

**MVP 결정**: 재랭킹 없이 RRF 결과 top-5 그대로 사용. Phase 2에서 cross-encoder 추가.

### 5.4 프롬프트 템플릿

```
[SYSTEM]
{guideline_loader.build_gpt_system_prompt() — 기존 함수 재사용}

[추가 RAG 지침]
- 아래 제공된 컨텍스트에 명시된 정보만 사용해 답변하시오.
- 컨텍스트에 없는 정보는 추측하지 말고 "해당 정보는 검토 자료에 포함되어 있지 않습니다"라고 답하시오.
- 답변 중 사용한 사실에는 반드시 [1], [2] 형식으로 인용 번호를 표기하시오.
- 의료법 면책조항을 응답 끝에 반드시 포함하시오:
  "{fixed_notices.bottom_disclaimer}"
- 응급 징후가 의심되면 답변 시작부에 "응급실/119 방문을 권유합니다"를 명시하시오.

[USER]
## 검토 자료
[1] {chunks[0].content} (출처: {chunks[0].source}, evidence: {chunks[0].evidence_level})
[2] {chunks[1].content} ...
[3] ...
[4] ...
[5] ...

## 질문
{user_query}
```

### 5.5 응답 가드레일 (post-generation)

```
응답 완성 직후:
  1. analyzer.py 호출 → ComplianceAnalyzer().analyze(response)
  2. CRITICAL 위반 발견 시:
     - 응답을 다음으로 교체:
       "죄송합니다. 안전 기준에 부합하는 응답을 생성하지 못했습니다.
        의료진과의 직접 상담을 권유합니다."
     - guardrail_action = 'blocked'
  3. HIGH 위반 발견 시 (최초 1회):
     - system 프롬프트에 "이전 응답에서 X 위반이 감지되었습니다. 절대 X를 포함하지 마시오." 추가
     - LLM 1회 재호출
     - guardrail_action = 'regenerated'
  4. 인용 검증:
     - 정규식 r'\[(\d+)\]' 매칭 → 사용된 번호가 retrieved chunks 범위 내인지 확인
     - 인용 0건이면 system에 "인용 누락" 경고 추가하고 1회 재생성
  5. 면책조항 검증:
     - fixed_notices.disclaimer_check_keywords 중 1개 이상 포함 확인
     - 누락 시 자동으로 응답 끝에 bottom_disclaimer 부착 (재생성 X, 비용 절감)
  6. 자문 결과 신규 가드레일 (2026-05-27 추가, 7명 자문위원 자문 결과 반영):
     - 갱년기 단정 표현 차단 (백은혜 자문)
     - 항생제 사용 기준 직접 설명 차단 (양현종 자문)
     - PHR 자기부정 차단 ("샘플 데이터" 등, 원성호 자문)
     - 1인칭 오용 차단 ("내가 60대 남성이라는 점", 원성호 자문)
     - 자해/자살 추측성 안내 차단 — 사용자 미언급 시 (백은혜 자문)
     - 응급 안내 + 추가 문진 동시 출력 차단 (최영호 자문)
     - 직접 검사 지시 차단 ("검사를 받으세요" 명령형) — 우회 표현으로 재생성
     상세 패턴: docs/expert_review_insights.md §3.1
```

### 5.6 4단 응답 구조 강제 (자문 반영, 신규)

시스템 프롬프트에 **4단 구조** 강제:

```
응답은 반드시 다음 4단 구조로 작성:

【① 즉시 행동】
가장 먼저 할 수 있는/해야 하는 행동 1-2가지

【② 의심 원인 요약】
가능성 높은 원인 2-3개 (단정 X, 가능성으로 표현)

【③ 상세 설명】
인용 [1][2]를 포함한 근거 설명

【④ 추가 확인 사항】
어떤 정보가 더 필요한지 + 진료 권유 시점

각 섹션은 헤더로 명확히 분리. "지금 할 수 있는 것"과 "이럴 때는 병원으로"가 혼재되지 않도록 한다.
```

→ **자문 핵심**: 자가관리와 병원 방문 권고가 혼재되면 사용자가 행동 기준 파악 불가 (홍승노·오범조 공통 지적). 4단 구조로 강제 분리.

### 5.7 EMERGENCY_REDIRECTED 상태머신 (자문 반영, 신규)

응급 안내 후 추가 문진을 차단하는 대화 상태 관리:

```
[대화 상태]
  IDLE → NORMAL → EMERGENCY_DETECTED → EMERGENCY_REDIRECTED → (사용자 새 질문 시 NORMAL 복귀)

[전환 조건]
- NORMAL → EMERGENCY_DETECTED: 응답에 red_flag 키워드 + 119/응급실 안내 동시 포함
- EMERGENCY_DETECTED → EMERGENCY_REDIRECTED: 위 응답 클라이언트 전송 직후

[EMERGENCY_REDIRECTED 상태에서의 응답 정책]
- 추가 문진 질문 일체 금지
- 같은 응급 안내만 반복 (사용자가 회피 시도 시)
- "119에 연락하셨나요?" 같은 확인성 질문만 허용
- LLM 호출 전 시스템 프롬프트에 상태 명시: "현재 응급 안내 후 상태. 추가 진단 정보 묻지 마시오."

[저장 위치]
- conversations 테이블에 신규 컬럼: emergency_state TEXT ('NORMAL'|'EMERGENCY_REDIRECTED')
- emergency_redirected_at TIMESTAMP
```

→ **자문 핵심**: 최영호(응급의학) "응급실/119 안내 후 추가 질문 이어가는 구조는 사용자와 평가자 모두에게 애매" 지적 직접 반영. 위험 안내 = 가점 X → 미이행 시 감점으로 격상 (오범조 자문).

---

## 6. LLM 라우터

### 6.1 추상 인터페이스

```python
# llm_router.py (신규)
class LLMProvider:
    """모든 프로바이더는 이 인터페이스를 구현"""

    def stream_chat(self, system: str, user: str,
                    max_tokens: int, temperature: float
                    ) -> Iterator[Dict]:
        """
        SSE 호환 청크 yield.
        형식: {"type": "GENERATION", "text": "..."}
              {"type": "STOP", "text": "(완성 응답)", "tokens": {"input": N, "output": N}}
              {"type": "ERROR", "message": "..."}
        """
        ...
```

### 6.2 지원 프로바이더 (Phase 별)

| 프로바이더 | 클래스 | Phase | 비고 |
|-----------|--------|-------|------|
| OpenAI | `OpenAIProvider` | 1 | 기존 `_evaluate_gpt`에 사용 중 — 패턴 재사용 |
| Anthropic | `AnthropicProvider` | 3 | claude-sonnet-4 / opus-4 |
| Vertex AI (Gemini) | `VertexProvider` | 4 | GCP 환경 동일 — IAM만 |
| Self-hosted (OpenAI-compatible) | `OpenAICompatibleProvider` | 4 | vLLM / TGI / Ollama 등 base_url 교체 |

### 6.3 설정 위치

- `settings.html`에 **신규 탭 추가**: "RAG 설정"
  - 서브 섹션 A: LLM 프로바이더 목록 (llm_providers 테이블 CRUD)
  - 서브 섹션 B: 활성 프로바이더 선택 (기본/배치/평가용 분리 가능)
  - 서브 섹션 C: 임베딩 모델 + 검색 파라미터 (top_k, alpha, ef_search)
- 기존 "GPT 설정" 탭은 **평가용**으로 유지 (혼동 방지)

### 6.4 메트릭 수집

- `rag_queries.cost_usd`: input/output 토큰 × `llm_providers.cost_per_1m_*` 자동 계산
- `rag_queries.latency_llm_ms` / `latency_retrieval_ms` 분리 기록
- 일별 집계 뷰 (선택, Phase 4):

```sql
CREATE VIEW v_rag_daily_metrics AS
SELECT date(created_at), llm_provider_id,
       count(*), avg(latency_total_ms), sum(cost_usd)
FROM rag_queries GROUP BY 1, 2;
```

---

## 7. API 설계 (신규 엔드포인트)

### 7.1 신규 엔드포인트 목록

| 메서드 | 경로 | 권한 | 설명 | 응답 형식 |
|--------|------|------|------|----------|
| POST | `/api/rag/chat` | 인증된 사용자 | 메인 RAG 응답 생성 | **SSE** (SKIX `_proxy_post`와 동일 포맷) |
| POST | `/api/rag/kb/ingest` | `manage_kb` | 문서 업로드 → 청킹 → 임베딩 → INSERT | JSON `{document_id, chunks_count, status}` |
| POST | `/api/rag/kb/ingest/batch` | `manage_kb` | ZIP/JSONL 일괄 업로드 | JSON `{job_id}` (비동기) |
| GET | `/api/rag/kb/documents` | `manage_kb` | KB 문서 목록 (페이지네이션, status 필터) | JSON 배열 |
| GET | `/api/rag/kb/documents/{id}` | `manage_kb` | 단일 문서 + 청크 미리보기 | JSON |
| PUT | `/api/rag/kb/documents/{id}` | `manage_kb` | 문서 수정 (재임베딩 트리거) | JSON |
| DELETE | `/api/rag/kb/documents/{id}` | `manage_kb` | 문서 + 청크 삭제 (CASCADE) | JSON |
| POST | `/api/rag/kb/approve` | `manage_kb` (의사) | 자체 콘텐츠 승인 → status=approved | JSON |
| POST | `/api/rag/kb/reject` | `manage_kb` (의사) | 거부 + 사유 | JSON |
| GET | `/api/rag/kb/sources` | `view_history` | 소스 목록 | JSON |
| GET | `/api/rag/queries/{id}` | `view_history` | 질의 감사 추적 (retrieval/citations/violations) | JSON |
| GET | `/api/rag/compare?scenario_id=X&run_id=Y` | `view_history` | SKIX vs RAG 동일 시나리오 비교 | JSON |
| GET | `/api/rag/providers` | Admin | LLM 프로바이더 목록 | JSON |
| POST | `/api/rag/providers` | Admin | 프로바이더 추가 | JSON |
| PUT | `/api/rag/providers/{id}` | Admin | 활성/비활성 토글 | JSON |
| POST | `/api/rag/providers/{id}/test` | Admin | 헬스체크 (1회 호출 테스트) | JSON `{ok, latency_ms, sample}` |
| GET | `/api/rag/search/preview` | `view_history` | 검색 단독 호출 (LLM 없이 retrieval만) — 디버깅용 | JSON 청크 배열 |

### 7.2 `POST /api/rag/chat` 요청/응답 명세

**요청 body** (SKIX 호환 + 확장):

```json
{
  "query": "열이 나고 머리가 아파요",
  "conversation_id": "uuid",
  "source_types": ["WEB", "PUBMED"],
  "provider_id": "openai_gpt4o",
  "top_k": 5,
  "enable_guardrails": true
}
```

**응답** (SSE, SKIX 호환):

```
data: {"type":"INFO","data":{"search_results":[{"chunk_id":"...","title":"발열","source":"kmle","score":0.87,"snippet":"..."}, ...]}}

data: {"type":"GENERATION","text":"발열 시"}
data: {"type":"GENERATION","text":"는 일반적으로 [1] "}
data: {"type":"GENERATION","text":"..."}

data: {"type":"STOP","text":"(전체 응답)","rag_query_id":"uuid","citations":[{"marker":"[1]","chunk_id":"..."}],"latency_ms":1234,"tokens":{"input":500,"output":150}}
```

→ **핵심 설계**: `chat_tester.html`의 SSE 파서가 SKIX 포맷을 이미 처리하므로 **클라이언트 코드 변경 최소화**. 새 필드 (`rag_query_id`, `citations`)는 STOP 이벤트에 부착해 후처리 단계에서만 사용.

---

## 8. A/B 비교 평가 통합

### 8.1 두 가지 경로

#### Path A: 채팅 테스터 즉시 비교 (단발성)

- `chat_tester.html`에서 토글 `mode="both"` 선택
- 클라이언트가 `Promise.all([fetch('/'), fetch('/api/rag/chat')])` 동시 호출
- 두 응답 모두 수신 후 side-by-side 렌더링
- 기존 평가 API (`/api/evaluate`, `/api/evaluate-consultation`) 양쪽에 호출

#### Path B: 시나리오 배치 비교 (대량)

- `scenario_manager.html`에서 배치 실행 시 옵션 추가: `comparisonMode: 'skix_only' | 'rag_only' | 'both'`
- 서버 측 `_run_batch_test()` 함수 (proxy_server.py line ~2300)에 분기 추가:
  - `both`: ThreadPoolExecutor에서 시나리오당 **2번** 실행 (SKIX 1회 + RAG 1회) → 결과 2개를 같은 `scenario_id` 아래 묶어 저장
  - 평가 시스템 (정규식+GPT+문진+composite_reward) 양쪽 동일 적용
- `test_runs.results` JSON 구조 확장:

```json
{
  "scenarioId": "...",
  "skix": { "response":"...", "scores":{}, "compositeReward": 0.62 },
  "rag":  { "response":"...", "scores":{}, "compositeReward": 0.74,
            "rag_query_id": "uuid", "citations": [] },
  "winner": "rag",
  "reward_delta": 0.12
}
```

- 기존 `results` 구조는 `skix` 키 하나만 있는 형태로 호환 (구버전 데이터 안 깨짐)

### 8.2 Arena 인프라 재사용

이미 `arena_model_configs` / `arena_sessions` / `arena_evaluations` 테이블이 존재 → **추가 설계 불필요**, 단지 새 slot 등록만:

```sql
INSERT INTO arena_model_configs (slot, label, use_env, endpoint_url, graph_type, ...)
VALUES ('rag_main', 'RAG (자체 시스템)', 'local', '/api/rag/chat', 'RAG', ...);
```

→ Chat Arena 페이지(`chat_arena.html`)에서 SKIX vs RAG 비교가 **추가 코드 없이** 가능.

### 8.3 자동 우열 판정 (Composite Reward)

- `composite_reward()` 함수 (proxy_server.py line 52) 그대로 사용
- 임계값: `reward_delta > 0.05`이면 winner 확정, 그 이하는 'tie'
- `preference_pairs` 자동 생성: winner를 `response_chosen`으로, 패자를 `response_rejected`로 INSERT (label_source='auto_composite')

---

## 9. UI 변경점 (HTML 파일별)

### 9.1 영향 분석 표

| 파일 | 영향도 | 예상 추가 라인 | 변경 내용 |
|------|--------|---------------|----------|
| `chat_tester.html` | 중 | ~80 | 엔드포인트 토글 (SKIX/RAG/Both), citations 렌더링, both 모드 split view |
| `settings.html` | 중 | ~250 | "RAG 설정" 6번째 탭 추가 (현재 5탭 → 6탭) |
| `history.html` | 중 | ~150 | both 결과 표시: skix/rag 컬럼 분할, citations 클릭 → 청크 펼침 |
| `scenario_manager.html` | 소 | ~30 | 배치 실행 시 `comparisonMode` 드롭다운 |
| `guideline_manager.html` | 소 | ~20 | "RAG 가드레일 미리보기" 버튼 |
| `chat_arena.html` (기존) | 소 | ~15 | RAG slot 자동 표시만 |
| **`kb_manager.html` (신규)** | 대 | ~1200 | KB CRUD + 의사 승인 큐 + 청크 미리보기 + 임베딩 상태 |

### 9.2 `kb_manager.html` 신규 페이지 구성

```
┌───────────────────────────────────────────────────────────┐
│  지식 베이스 관리                       [+ 문서 추가]      │
├──────────┬────────────────────────────────────────────────┤
│  필터    │  목록 (페이지네이션)                            │
│ 소스 ▼   │  ┌────────────────────────────────────────┐   │
│ 상태 ▼   │  │ 발열 환자 평가 [KMLE][active][A]       │   │
│ 증상 ▼   │  │   청크 12개 · 2026-04-01 · 김의사       │   │
│ 검색     │  ├────────────────────────────────────────┤   │
│          │  │ 두통 감별진단 [내부][pending][B]       │   │
│          │  │   청크 8개 · 작성중 · 박원장            │   │
│          │  │              [승인] [거부] [수정]       │   │
│          │  ├────────────────────────────────────────┤   │
│          │  │ ...                                    │   │
│          │  └────────────────────────────────────────┘   │
└──────────┴────────────────────────────────────────────────┘

[문서 상세 모달]
  - 마크다운 원본 편집
  - 메타데이터 폼 (symptom_tags, age_group, severity, evidence_level)
  - 청크 미리보기 (분할 결과 확인)
  - [재임베딩] 버튼
  - [검색 미리보기] — 이 문서가 어떤 질의에서 노출되는지 테스트
```

### 9.3 클라이언트 코드 패턴 (CLAUDE.md 준수)

- 들여쓰기 2칸, camelCase
- DOM null 체크 필수
- innerHTML + JSON.stringify 직접 삽입 금지 → `addEventListener + 클로저`
- 평가 결과 폰트 규칙은 RAG citations에도 동일 적용 (헤더 14-15px, 본문 13px, 상세 12px)

---

## 10. 의료법·법적 고려사항

### 10.1 출처 명시 강제 (필수)

- 응답 내 `[N]` 인용 마커 **0건이면 가드레일이 차단**
- 클라이언트 UI에서 `[N]` 클릭 시 해당 청크의 `source_id` + `last_verified_date` + URL 표시
- `rag_queries.citations_json`에 영구 기록 → 사후 감사 가능

### 10.2 의사 검수 워크플로

- 자체 콘텐츠 (`source_type='internal'`)는 **반드시** `manage_kb` 권한 보유 의사가 승인
- 자동 ingest 경로 차단 (UI 강제: status=draft → 수동 승인만 가능)
- 승인자 ID + 일시 영구 기록 (kb_documents.approved_by, approved_at)

### 10.3 라이선스 추적

| 소스 | 라이선스 | 검증 책임 |
|------|---------|----------|
| KMLE | 사용 전 대한의학회 라이선스 문의 필요 | Admin (수동 검증 후 source 등록) |
| PubMed Abstract | 대부분 public domain | source.license='public_domain' 기록 |
| HIRA/KDCA | 공공누리(KOGL) Type 1: 출처 표시 시 자유 | source.license='kogl_type1' |
| 자체 콘텐츠 | 병원과 별도 계약 (proprietary) | 계약서 파일 별도 보관 |

- `kb_sources.license` 필드로 추적, UI에 표시
- PubMed 등 라이선스 불명확 자료는 **MVP에서 제외** (라이선스 검증 완료된 자료만 시드)

### 10.4 개인정보·민감정보 로깅 정책

- `rag_queries.query_text`: 사용자 질의는 **민감정보** (증상 = 건강정보)
- 자동 마스킹: 질의 저장 전 정규식으로 주민번호/전화번호/이메일 마스킹
- 보존 기간: 90일 후 자동 삭제 (cron 또는 cleanup 작업)
- 의료법 제19조 (비밀 누설 금지) 인식: 외부 LLM 호출 시 PII가 외부로 흘러나가지 않는지 점검

### 10.5 의료법 제27조 경계 재확인

- RAG는 **정보 제공**까지만. **진단 단정 / 처방 지시 금지** — 기존 `analyzer.py` 위반 패턴이 가드레일에서 차단 보장
- 응답 끝 면책조항 자동 첨부 (생략 절대 불가)

---

## 11. 단계별 구현 로드맵 (Phase 1~4)

### Phase 1 — KB 인프라 + 단일 LLM RAG MVP (예상 2~3주)

**목표**: 가장 단순한 RAG 작동, OpenAI 1개로 응답 생성, 채팅 테스터에서 SKIX와 토글 가능

**산출물**:

- 신규 파일:
  - `rag_engine.py` (검색 + 합성 메인)
  - `embedding_provider.py` (BGE-M3 또는 OpenAI 임베딩 추상화)
  - `llm_router.py` (인터페이스 + OpenAIProvider만)
  - `kb_ingest.py` (청킹 + 임베딩 INSERT)
  - `kb_manager.html` (KB CRUD 페이지, 단순 버전)
- 수정 파일:
  - `db.py`: 6개 신규 테이블 추가 (pgvector 활성화 포함)
  - `proxy_server.py`: `/api/rag/chat`, `/api/rag/kb/*` 라우트 추가 (~300줄)
  - `chat_tester.html`: 엔드포인트 토글 (~50줄)
  - `requirements.txt`: `psycopg2-binary[pgvector]` 또는 `pgvector` 패키지
- DB 마이그레이션 스크립트: `migrations/001_rag_tables.sql`

**검증 기준**:

- 50개 시드 문서 ingest → 청크 ≥ 300개 생성
- 채팅 테스터에서 "발열" 질의 → 응답 + 인용 ≥ 1개
- 가드레일 동작 확인 (CRITICAL 위반 응답 차단)
- `rag_queries` 테이블에 모든 호출이 기록

**예상 작업 단위**: 약 8개 PR / 약 60시간

---

### Phase 2 — 가드레일 강화 + A/B 비교 평가 (예상 2주)

**목표**: 안전성 강화 + SKIX와 자동 비교

**산출물**:

- 수정: `analyzer.py` — RAG 후처리에서 직접 호출되도록 함수 형태 정리
- 수정: `proxy_server.py` `_run_batch_test` — `comparisonMode='both'` 분기 (~150줄)
- 수정: `history.html` — side-by-side 비교 뷰 (~150줄)
- 수정: `chat_tester.html` — `mode='both'` UI (~80줄)
- 수정: `scenario_manager.html` — 비교 드롭다운 (~30줄)
- 신규: `rag_engine.py` — cross-encoder 재랭킹 (옵션)
- 신규: 자동 `preference_pairs` 생성 로직 (winner/loser 기반)

**검증 기준**:

- 시나리오 100개 배치 (`both` 모드) → 결과 모두 SKIX/RAG 양쪽 점수 보유
- `preference_pairs` 자동 INSERT 확인
- Composite Reward 평균이 RAG ≥ SKIX (G1 목표)

**예상 작업 단위**: 약 6개 PR / 약 45시간

---

### Phase 3 — LLM 라우터 + 의사 승인 워크플로 (예상 2주)

**목표**: 다중 LLM 비교 + 자체 콘텐츠 안전 워크플로

**산출물**:

- 신규: `AnthropicProvider`, `VertexProvider` 추가
- 수정: `settings.html` — "RAG 설정" 탭 (~250줄)
- 신규: 권한 코드 `manage_kb` 추가 (proxy_server.py PERMISSION_CATALOG)
- 확장: `kb_manager.html` — 의사 승인 큐, 거부 사유, 변경 이력
- 신규: `/api/rag/kb/approve|reject` 엔드포인트

**검증 기준**:

- 같은 질의 → 3개 프로바이더에서 응답 생성 → 비교 가능
- 의사 권한 사용자만 `pending_review` 상태 변경 가능 (권한 테스트)
- 거부 시 이메일/알림 (Phase 4로 미룰 수 있음)

**예상 작업 단위**: 약 5개 PR / 약 40시간

---

### Phase 4 — 운영 최적화 (예상 2주)

**목표**: 비용·성능·관측성

**산출물**:

- 임베딩 캐시 (질의별 해시 → 24시간 TTL, Redis 또는 SQLite L1)
- LLM 응답 캐시 (질의 + provider + chunk_ids 조합 해시)
- 로그 집계 뷰 (`v_rag_daily_metrics`)
- `/api/rag/queries/{id}` 디버깅 UI (chat_tester 사이드패널에서 호출)
- 비용 알림 (일일 임계값 초과 시 settings 페이지 배너)
- HNSW 인덱스 재빌드 스크립트 (청크 50K 돌파 시)
- PII 마스킹 정규식 + 90일 retention cron

**검증 기준**:

- 동일 질의 2회차 latency < 200ms (캐시 hit)
- 일일 비용 대시보드 표시
- PII 마스킹 적용된 로그 확인

**예상 작업 단위**: 약 5개 PR / 약 35시간

---

## 12. 리스크 & 완화

| # | 리스크 | 발생 확률 | 영향 | 완화책 |
|---|--------|----------|------|--------|
| R1 | **잘못된 검색 → 잘못된 응답** (할루시네이션) | 중 | 치명 | (a) 인용 강제, (b) "컨텍스트에 없으면 모른다" 시스템 프롬프트, (c) Phase 2 재랭킹, (d) 가드레일 후처리 |
| R2 | **PubMed/KMLE 라이선스 위반** | 중 | 치명 | MVP는 라이선스 검증 완료 자료만. `kb_sources.license` 추적. 의심 시 의료법 자문 |
| R3 | **pgvector 성능 한계** (수십만 청크) | 저 | 중 | HNSW 인덱스, 청크 50K마다 모니터링, 1M 돌파 시 외부 벡터 DB (Qdrant/Weaviate) 검토 |
| R4 | **LLM 비용 폭증** | 중 | 중 | (a) `llm_providers.cost_per_1m_*` 추적, (b) 일일 알림, (c) 캐시 hit ratio 모니터링, (d) 배치는 저비용 모델 (gpt-4o-mini) 기본 |
| R5 | **SKIX 대비 응답 지연** | 고 | 저 | retrieval은 100ms 이하 목표 (HNSW). LLM은 모델 선택 영향이 큼 → 스트리밍으로 체감 지연 완화 |
| R6 | **자체 콘텐츠 의료적 오류** | 중 | 치명 | 의사 reviewer 승인 워크플로 절대 우회 불가, 거부 사유 강제 기록 |
| R7 | **DB 마이그레이션 실패** (PostgreSQL pgvector 미설치) | 저 | 고 | 마이그레이션 스크립트 첫 줄에 `CREATE EXTENSION` 포함, deploy.ps1에 Cloud SQL flag 확인 단계 추가 |
| R8 | **SSE 스트리밍 비호환** (LLM 프로바이더별 차이) | 중 | 중 | `LLMProvider.stream_chat` 어댑터에서 통일 포맷으로 정규화. 비스트리밍 프로바이더는 한꺼번에 GENERATION 1회로 전송 |
| R9 | **PostgreSQL ↔ SQLite 듀얼 모드 깨짐** | 중 | 중 | SQLite는 벡터 검색 불가 → 개발 모드에서는 RAG 라우트가 503 반환. 명확한 에러 메시지 |
| R10 | **Cloud Run min-instance 0에서 임베딩 cold start** | 중 | 저 | 임베딩은 외부 OpenAI API로 fallback (BGE-M3 자체호스팅 대신). 자체호스팅은 Phase 4+ |

---

## 13. 의사결정 필요 항목 (Open Questions)

사용자 확정 필요 (Phase 1 착수 전 답변 요청):

1. ~~**임베딩 모델 최종 선택**~~ → ✅ **확정**: Phase 1 MVP는 **OpenAI text-embedding-3-small**, Phase 4에 **BGE-M3**로 단계별 마이그레이션. 상세: [embedding_migration_strategy.md](./embedding_migration_strategy.md)
2. ~~**Phase 1 LLM 1개 선택**~~ → ✅ **확정**: **GPT-5 (메인) + GPT-5-mini (재생성·배치)** 듀얼 등록. `llm_providers` 테이블 시드 시 두 프로바이더 모두 INSERT. 환경변수 `RAG_LLM_MODEL=gpt-5`, `RAG_LLM_FALLBACK_MODEL=gpt-5-mini`.
3. ~~**초기 KB 시드 규모**~~ → ✅ **확정**: 50문서 (의사 10 + 공공 30 + 의학회 10) → 청크 ~300개 목표
4. ~~**자체 콘텐츠 작성자**~~ → ✅ **확정**: 의사(사용자) 직접 작성. UI는 medical-expert 권한 사용자가 직접 입력 + Admin 승인 워크플로
5. ~~**라이선스 검증 책임**~~ → ✅ **확정**: Admin이 사전 검증. PubMed는 Phase 1 제외, 대한의학회만 사전 문의
6. ~~**Phase 1 데드라인**~~ → ✅ **확정**: 3주, **2026-06-17** 완료
7. **벡터 DB 호스팅** (대기 중): 2026-05-27 인프라팀 확인 요청 발송. PostgreSQL 버전·`cloudsql.enable_pgvector` 권한·인스턴스 사양·EXTENSION 권한 4개 항목 회신 대기.

---

## 부록 A: 기존 자산 재사용 매핑표

| 기존 자산 | 어디서 재사용 | 어떻게 |
|-----------|--------------|--------|
| `guidelines.json` | 프롬프트 빌더 + 가드레일 | `guideline_loader.build_gpt_system_prompt()` 그대로 호출, `fixed_notices`를 응답 끝에 자동 첨부 |
| `violation_rules.json` (42패턴) | post-generation 가드레일 | `analyzer.py ComplianceAnalyzer().analyze(response)` 그대로 호출 |
| `consultation_checklists.json` (42 증상) | **검색 부스팅** + 프롬프트 + 평가 | (a) red_flags 키워드로 청크 점수 ×1.3, (b) 매칭된 symptom의 required_questions를 시스템 프롬프트에 주입, (c) 기존 `_evaluate_consultation_checklist`는 변경 없이 그대로 |
| `composite_reward()` | A/B 자동 우열 판정 | `proxy_server.py:52` 함수 그대로 호출 |
| `_evaluate_gpt()` / `_evaluate_consultation()` | RAG 응답 평가 | 변경 없음. SKIX와 동일하게 RAG 응답에도 적용 |
| `_check_compliance()` | RAG 가드레일 + 평가 | 변경 없음. 가드레일 단계에서 호출 |
| `arena_model_configs` 테이블 | RAG vs SKIX 비교 인프라 | 새 slot 등록만으로 chat_arena.html에서 즉시 사용 |
| `response_feedback` 테이블 | RAG 응답 피드백 | message_id 매칭으로 그대로 작동 |
| `preference_pairs` 테이블 | RLHF 데이터셋 | A/B 비교에서 자동 생성 (label_source='auto_composite' 추가) |
| `test_runs.results` JSON | 배치 결과 저장 | 스키마는 그대로, `skix`/`rag` 키를 results 아이템에 추가 |
| `_run_batch_test` ThreadPoolExecutor | 양쪽 동시 호출 | 시나리오당 2번 submit으로 변경, 동일 풀 재사용 |
| 권한 시스템 (`PERMISSION_CATALOG`) | KB 관리 권한 | `manage_kb` 코드만 신규 추가, 검사 로직은 동일 |
| Cloud Run + VPC NAT 고정 IP | LLM API 호출 | 변경 없음. OpenAI/Anthropic 호출도 동일 NAT 경유 |

---

## 부록 B: 최종 권고

1. **이번 기획은 SKIX를 대체하지 않는다** — 병렬 운영으로 시작해, Composite Reward 비교 결과가 안정적 우위(예: 3개월 평균 +0.10 이상)를 보일 때까지 단계적 확장.
2. **Phase 1 시작 전, Open Questions 7개 모두 확정 후 착수 권장**. 특히 pgvector 호스팅 가능 여부(Q7)는 인프라팀 확인이 필요해 가장 먼저 답이 와야 함.
3. **다음 단계 (사용자 결정 후)**: 본 기획서를 바탕으로 Phase 1 작업 분해표 + 서브에이전트 태스크 목록 생성.
