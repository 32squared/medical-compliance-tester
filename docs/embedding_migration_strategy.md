# 임베딩 모델 전환 전략 (OpenAI → BGE-M3)

**관련 문서**: [rag_architecture.md](./rag_architecture.md)
**작성일**: 2026-05-27
**전략**: MVP는 OpenAI text-embedding-3-small로 빠르게 시작 → BGE-M3 자체호스팅으로 단계별 마이그레이션
**핵심 원칙**: **각 전환 단계마다 사용자 명시적 승인 필수. 자동 전환 절대 없음.**

---

## 0. 한눈에 보는 전환 흐름

```
[Phase 1 MVP]                [Phase 2~3 운영]          [Phase 4 마이그레이션]
                                                                                  
 OpenAI small  ──────────►   OpenAI small ──────►   OpenAI + BGE-M3 듀얼 ──►  BGE-M3
 (1536차원)                  (트래픽 안정화)         (검증 기간)                  (1024차원)
     │                             │                       │                       │
     ▼                             ▼                       ▼                       ▼
  ☐ Check 1                    ☐ Check 2              ☐ Check 3,4,5            ☐ Check 6,7
  MVP 시작                     운영 안정성             듀얼 인덱싱·A/B           정식 전환
  승인                         확인                     비교·트래픽 분할          ·OpenAI 제거
```

---

## 1. 아키텍처: 모델 교체 가능한 추상화 계층

### 1.1 핵심 추상화 (`embedding_provider.py` — 신규 모듈)

```python
# embedding_provider.py
class EmbeddingProvider:
    """모든 임베딩 모델이 따라야 하는 인터페이스"""

    @property
    def model_id(self) -> str:
        """예: 'openai_small_v3', 'bge_m3'"""
        ...

    @property
    def dimension(self) -> int:
        """벡터 차원 (1536 / 1024 / 3072 등)"""
        ...

    def embed(self, texts: list[str]) -> list[list[float]]:
        """배치 임베딩. 1개~N개 텍스트 → 벡터 리스트"""
        ...

    def health_check(self) -> dict:
        """{'ok': bool, 'latency_ms': int, 'sample_dim': int}"""
        ...


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """text-embedding-3-small (Phase 1 기본)"""
    model_id = "openai_small_v3"
    dimension = 1536
    # ...

class BGEM3EmbeddingProvider(EmbeddingProvider):
    """자체호스팅 BGE-M3 (Phase 4+)"""
    model_id = "bge_m3"
    dimension = 1024
    base_url: str  # 자체호스팅 서버 URL
    # ...


# 라우팅 진입점
def get_embedding_provider(slot: str = "default") -> EmbeddingProvider:
    """
    slot:
      - 'default'   → 검색 시 사용
      - 'ingest'    → KB ingest 시 사용 (마이그레이션 중에는 양쪽 다 호출)
      - 'shadow'    → 듀얼 인덱싱 검증용
    """
    config = db.get_active_embedding_provider(slot)  # 신규 settings 테이블
    if config.provider == "openai":
        return OpenAIEmbeddingProvider(config)
    elif config.provider == "bge_m3":
        return BGEM3EmbeddingProvider(config)
    raise ValueError(f"Unknown provider: {config.provider}")
```

### 1.2 DB 스키마 보강 (rag_architecture.md의 6개 테이블에 추가)

**기존 `kb_chunks` 테이블 수정**:

```sql
-- 기존
embedding vector(1024)

-- 변경: 마이그레이션 동안 두 벡터를 동시에 보유
embedding_primary vector(1536),       -- 현재 활성 모델 (Phase 1: OpenAI)
embedding_secondary vector(1024),     -- 새 모델 (Phase 4: BGE-M3)
embedding_primary_model TEXT,         -- 'openai_small_v3'
embedding_secondary_model TEXT,       -- 'bge_m3' (NULL이면 듀얼 모드 아님)
secondary_indexed_at TEXT             -- 보조 임베딩 생성 시점
```

→ pgvector는 한 컬럼이 한 차원만 가질 수 있음. **차원이 다른 두 모델을 동시 운영하려면 컬럼 2개 필수**.

**신규 테이블 — 임베딩 프로바이더 설정**:

```sql
CREATE TABLE embedding_providers (
    slot TEXT PRIMARY KEY,                -- 'default' | 'ingest' | 'shadow'
    provider TEXT NOT NULL,               -- 'openai' | 'bge_m3'
    model_id TEXT NOT NULL,
    dimension INTEGER NOT NULL,
    base_url TEXT,                        -- 자체호스팅용
    api_key_encrypted TEXT,
    is_active INTEGER DEFAULT 1,
    -- 마이그레이션 상태
    migration_status TEXT DEFAULT 'stable',  -- 'stable' | 'dual_indexing' | 'shadow_eval' | 'rollout' | 'migrating' | 'rollback'
    rollout_percentage INTEGER DEFAULT 0,    -- 0~100, 신규 모델 사용 비율
    last_changed_by TEXT,                    -- 변경 승인한 사용자 ID
    last_changed_at TEXT NOT NULL
);
```

**신규 테이블 — 마이그레이션 작업 로그 (감사 추적)**:

```sql
CREATE TABLE embedding_migration_log (
    id TEXT PRIMARY KEY,
    checkpoint TEXT NOT NULL,             -- 'check_1' ~ 'check_7'
    from_state TEXT,
    to_state TEXT,
    triggered_by TEXT NOT NULL,           -- 사용자 ID
    approved_at TEXT NOT NULL,
    rollback_plan TEXT,                   -- 이 단계 롤백 방법
    metrics_json TEXT,                    -- 비용·시간·품질 지표
    notes TEXT
);
```

### 1.3 검색 함수의 모델 인지 (`rag_engine.py`)

```python
def hybrid_search(query, top_k=20):
    provider = get_embedding_provider("default")
    q_emb = provider.embed([query])[0]

    # 어떤 컬럼을 조회할지 동적 결정
    column = "embedding_primary" if provider.model_id == get_active_primary_model() \
             else "embedding_secondary"

    sql = f"""
        SELECT id, 1 - ({column} <=> %s::vector) AS score
        FROM kb_chunks
        WHERE {column}_model = %s
          AND ...
        ORDER BY {column} <=> %s::vector
        LIMIT 20
    """
    # ...
```

→ **모델 ID로 안전장치**: 검색 시 청크의 임베딩이 현재 사용 중인 모델로 생성된 것인지 확인. 차원 불일치 시 pgvector가 즉시 에러를 던지므로 데이터 무결성 자동 보장.

---

## 2. 단계별 마이그레이션 로드맵 (Checkpoint 포함)

### 🔵 단계 0: Phase 1 MVP 시작 — Check 1

**상태**: OpenAI text-embedding-3-small 단독 운영
**시점**: Phase 1 착수 시점 (~2026-06-01)

#### 사전 준비
- [ ] OpenAI API 키 발급 + Cloud Secret Manager 등록
- [ ] PII 마스킹 정규식 검토 (주민번호/전화번호/이메일)
- [ ] OpenAI 약관 확인 (학습 데이터 미사용 옵션 활성화)

#### ☑️ **Check 1: MVP 임베딩 모델 확정**
| 확인 항목 | 담당 | 상태 |
|----------|------|------|
| OpenAI small을 MVP 임베딩 모델로 확정 | **사용자** | ☐ |
| `embedding_providers` 테이블에 `slot='default', provider='openai', model_id='text-embedding-3-small'` INSERT | DevOps | ☐ |
| PII 마스킹 적용 여부 확인 (테스트 질의로 검증) | QA | ☐ |
| 첫 KB 50문서 ingest 후 검색 동작 확인 | 의료 reviewer | ☐ |

**롤백 계획**: N/A (MVP 시작 단계)

**승인란**:
```
승인자: ______________  날짜: ______________  사인: ______________
```

---

### 🟢 단계 1: 운영 안정화 — Check 2

**상태**: OpenAI small 운영 중, 트래픽·비용·품질 데이터 축적
**시점**: Phase 1 종료 ~ Phase 3 (약 2~3개월)

#### 수집할 지표
- 일평균 질의 수
- 일평균 임베딩 API 비용
- 평균 검색 지연 (retrieval_ms)
- KB 청크 총 수
- 의사 reviewer의 검색 품질 피드백 (kb_feedback 테이블)

#### ☑️ **Check 2: BGE-M3 전환 필요성 판단**
| 판단 기준 | 임계값 | 현재값 | 통과? |
|----------|--------|--------|-------|
| 월 OpenAI 비용 > $50? | YES면 전환 검토 | $___ | ☐ |
| 의료 PII 외부 송신 차단 요구사항 발생? | YES면 전환 필수 | ___ | ☐ |
| KB 청크 > 30,000? | YES면 자체호스팅 ROI 개선 | ___ | ☐ |
| BGE-M3 호스팅 인프라 예산 확보? | $30~80/월 | ___ | ☐ |
| 의사 reviewer가 검색 품질 개선 요청? | 정성 평가 | ___ | ☐ |

**판단**: 위 5개 중 **2개 이상 YES**이면 Check 3으로 진행, 그렇지 않으면 OpenAI 유지.

**승인란**:
```
판단 결과: [ ] 전환 진행   [ ] OpenAI 유지
승인자: ______________  날짜: ______________  사인: ______________
```

---

### 🟡 단계 2: BGE-M3 인프라 준비 — Check 3

**상태**: BGE-M3 서비스 구축 중. 운영 트래픽은 여전히 OpenAI.
**시점**: Check 2 승인 후 ~2주

#### 작업 내용
- BGE-M3 컨테이너 이미지 빌드 (`Dockerfile.embedding`)
- Cloud Run 별도 서비스 배포 (`embedding-bge-m3`)
- 헬스체크 엔드포인트 (`/health`, `/embed`)
- VPC NAT 내부 통신 확인

#### ☑️ **Check 3: BGE-M3 인프라 검증**
| 확인 항목 | 검증 방법 | 통과 기준 | 통과? |
|----------|----------|----------|-------|
| BGE-M3 서비스 헬스체크 | `curl https://embedding-bge-m3/health` | 200 OK, dimension=1024 | ☐ |
| 임베딩 응답 지연 | 100회 호출 평균 | < 500ms (CPU), < 100ms (GPU) | ☐ |
| 동시성 부하 테스트 | 10 동시 요청 | 모두 성공 | ☐ |
| 비용 추정 | Cloud Run 청구서 (1주) | 예산 내 | ☐ |
| Cold start 시간 | min-instance=0 상태 | < 60초 (수용 가능) | ☐ |
| 자체호스팅 임베딩 결과 일관성 | 같은 입력 → 같은 벡터 | 코사인 유사도 = 1.0 | ☐ |

**롤백 계획**: BGE-M3 서비스 삭제. 운영 트래픽 영향 없음 (아직 사용 안 함).

**승인란**:
```
승인자: ______________  날짜: ______________  사인: ______________
비고: ______________________________________________
```

---

### 🟡 단계 3: 듀얼 인덱싱 시작 — Check 4

**상태**: KB 전체를 BGE-M3로 재임베딩. 검색은 여전히 OpenAI 기준.
**시점**: Check 3 승인 후 즉시 ~ 청크 수에 비례 (예상: 5,000 청크 = 2~4시간)

#### 작업 내용
- `kb_chunks.embedding_secondary` 컬럼 활성화
- `kb_chunks.embedding_secondary_model = 'bge_m3'` 설정
- 백그라운드 작업: 모든 청크를 BGE-M3로 재임베딩
- 신규 ingest는 양쪽 모델로 동시 임베딩 (이중 쓰기)
- 진행률 UI 표시

#### 비용·시간 사전 추정 (사용자에게 보여줘야 할 정보)

| KB 청크 수 | 추정 BGE-M3 임베딩 시간 | 추정 OpenAI 임베딩 비용* | 디스크 추가 사용 |
|-----------|----------------------|------------------------|------------------|
| 5,000 | 2~4시간 (CPU) / 20분 (GPU) | $0 (재계산 안 함) | ~30MB |
| 50,000 | 1~2일 (CPU) / 3시간 (GPU) | $0 | ~300MB |
| 500,000 | 2주 (CPU) / 1일 (GPU) | $0 | ~3GB |

*BGE-M3는 자체호스팅이므로 임베딩 자체 비용은 0. 시간만 소요.

#### ☑️ **Check 4: 듀얼 인덱싱 시작 승인**
| 확인 항목 | 통과? |
|----------|-------|
| 현재 KB 청크 수: _______ | ☐ |
| 추정 시간 검토 (위 표 참고): _______ 시간 | ☐ |
| 백그라운드 작업이 운영 트래픽에 영향 없음 확인 (rate limit) | ☐ |
| 작업 중단 가능 여부 (resume 지원) | ☐ |
| `kb_chunks` 디스크 추가 사용량 허용 범위 | ☐ |

**롤백 계획**:
- 듀얼 인덱싱 중단: `UPDATE embedding_providers SET migration_status='stable' WHERE slot='shadow'`
- 보조 컬럼 데이터 삭제: `UPDATE kb_chunks SET embedding_secondary=NULL, embedding_secondary_model=NULL`
- **운영 트래픽 영향 없음** (검색은 여전히 primary 컬럼만 사용)

**승인란**:
```
시작 시각: ______________  완료 예상 시각: ______________
승인자: ______________  날짜: ______________  사인: ______________
```

---

### 🟠 단계 4: A/B 검색 품질 비교 (Shadow 평가) — Check 5

**상태**: 운영 트래픽은 여전히 OpenAI. 백그라운드에서 BGE-M3로도 검색 실행해 결과 비교.
**시점**: 듀얼 인덱싱 완료 후 ~2주

#### 작업 내용
- 모든 실제 질의에 대해 **두 모델 모두로 검색 수행**
- 결과만 `embedding_shadow_eval` 테이블에 기록 (사용자에게 보이지 않음)
- 자동 지표 + 의사 reviewer 정성 평가

#### 측정 지표

| 지표 | 측정 방법 | BGE-M3 목표 |
|------|----------|------------|
| **Top-5 겹침률** (Jaccard) | 같은 질의에서 양쪽 top-5 결과의 교집합 비율 | ≥ 60% (완전히 다르면 의심) |
| **MRR@5** (Mean Reciprocal Rank) | 의사 reviewer가 "맞는 청크"라고 라벨한 결과의 평균 역순위 | ≥ OpenAI MRR |
| **응급 청크 회상률** | red_flag 키워드 포함 청크가 top-5에 들어오는 비율 | ≥ 95% |
| **평균 검색 지연** | retrieval_ms | ≤ OpenAI + 100ms |
| **사례별 우열** | 100개 샘플 의사 blind review | BGE-M3 승률 ≥ 40% (호각) |

#### ☑️ **Check 5: BGE-M3 품질 검증**
| 지표 | 측정값 | 목표 통과? |
|------|--------|----------|
| Top-5 Jaccard | _____% | ☐ |
| MRR@5 (BGE / OpenAI) | _____ / _____ | ☐ |
| 응급 청크 회상률 | _____% | ☐ |
| 평균 지연 차이 | +_____ ms | ☐ |
| 의사 blind review (BGE 승/무/패) | _____ / _____ / _____ | ☐ |

**판단 매트릭스**:
- 5개 지표 중 **4개 이상 통과** → Check 6 진행
- **2~3개 통과** → 1주 추가 데이터 수집, 재평가
- **1개 이하** → BGE-M3 설정 재검토 (청킹 전략, 정규화 등) 또는 마이그레이션 중단

**롤백 계획**: 평가만 한 상태이므로 영향 없음. 결정이 "중단"이면 듀얼 인덱싱 데이터를 보존(다음 기회에 재평가) 또는 삭제.

**승인란**:
```
판단 결과: [ ] Check 6 진행   [ ] 추가 평가   [ ] 마이그레이션 중단
승인자: ______________  날짜: ______________  사인: ______________
```

---

### 🔴 단계 5: 점진적 트래픽 전환 (Canary Rollout) — Check 6

**상태**: 실제 사용자 트래픽 중 일부를 BGE-M3로 라우팅. 비율을 단계적으로 증가.
**시점**: Check 5 승인 후 4단계 진행 (각 단계 최소 3~7일)

#### Rollout 단계

| 단계 | BGE-M3 비율 | 기간 | 모니터링 |
|------|-----------|------|----------|
| 5-A | 10% | 3일 | 에러율, 지연, 의사 피드백 |
| 5-B | 30% | 5일 | + 검색 품질 자동 지표 |
| 5-C | 50% | 7일 | + composite_reward 비교 |
| 5-D | 100% | 7일 | 모든 지표 |

#### 자동 롤백 조건 (서버 자동 감지)
다음 중 하나라도 발생 시 BGE-M3 비율을 **즉시 0%로 자동 되돌리고 사용자에게 알림**:
- 5분간 BGE-M3 검색 에러율 > 1%
- 평균 지연이 OpenAI 대비 +500ms 초과
- 의사 reviewer가 `kb_feedback`에 'wrong_info' 5건 이상 신고

#### ☑️ **Check 6: 각 단계별 승인** (4번 반복)

**단계 5-A (10% rollout)**:
| 확인 항목 | 통과? |
|----------|-------|
| 자동 롤백 감지 동작 테스트 (시뮬레이션) | ☐ |
| 모니터링 대시보드 URL 확인 | ☐ |
| 알림 채널 (Slack/이메일) 동작 | ☐ |
| 의사 reviewer가 변경 사실 인지 | ☐ |

```
시작: ______________  종료: ______________
승인자: ______________  사인: ______________
```

**단계 5-B (30%)**:
| 확인 항목 | 측정값 | 통과? |
|----------|--------|-------|
| 10% 기간 동안 자동 롤백 발생? | YES/NO | ☐ NO여야 통과 |
| BGE-M3 에러율 | _____% | ☐ < 0.5% |
| 평균 composite_reward 차이 | +/- _____ | ☐ ≥ -0.05 |

```
승인자: ______________  사인: ______________
```

**단계 5-C (50%)**: (5-B와 동일 양식)
**단계 5-D (100%)**: (5-B와 동일 양식)

---

### 🟣 단계 6: OpenAI 임베딩 제거 (정식 전환) — Check 7

**상태**: 모든 트래픽이 BGE-M3로 흐름. OpenAI 임베딩 컬럼·서비스 제거.
**시점**: 단계 5-D 완료 후 최소 **30일 안정 운영** 후

#### ⚠️ 이 단계는 **롤백이 어렵습니다** (재임베딩 필요)

#### 작업 내용
- `kb_chunks.embedding_primary` 컬럼을 BGE-M3 데이터로 덮어쓰기 (또는 컬럼 swap)
- `kb_chunks.embedding_secondary` 컬럼 NULL 처리 (또는 삭제)
- OpenAI 임베딩 API 키 회수 (이제 임베딩에는 미사용, LLM에는 계속 사용)
- 비용 절감 확인

#### ☑️ **Check 7: 정식 전환 최종 승인**
| 확인 항목 | 통과? |
|----------|-------|
| 100% rollout 후 30일 무사고 운영 확인 | ☐ |
| 최근 30일 의사 reviewer 부정 피드백 < 5건 | ☐ |
| 최근 30일 의료법 위반 감지 건수 ≤ OpenAI 시기 평균 | ☐ |
| OpenAI 임베딩 의존 코드 전부 제거됨 (grep 확인) | ☐ |
| 비용 절감 효과 확인 (월 비교) | ☐ |
| 백업: 전환 직전 DB 스냅샷 생성 | ☐ |

**롤백 계획** (이 단계 이후 롤백):
- DB 스냅샷에서 복구 → 청크 전체 OpenAI로 재임베딩 필요 (시간·비용 소요)
- 예상 비용: 5,000 청크 = ~$0.3, 50,000 청크 = ~$3
- 예상 시간: 1~24시간 (API rate limit에 따라)

**승인란**:
```
최종 승인자 (Admin 필수): ______________  날짜: ______________  사인: ______________
DB 백업 위치: ______________________________________________
```

---

## 3. UI에서 어떻게 체크하는가

### 3.1 `settings.html` → 신규 "RAG 설정" 탭 → "임베딩 모델 마이그레이션" 섹션

```
┌─────────────────────────────────────────────────────────────────┐
│ 임베딩 모델 마이그레이션                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│ 현재 상태:  ▓▓▓▓▓░░░░░  단계 3 (듀얼 인덱싱)                    │
│                                                                 │
│ ┌───────────┬─────────────────────────┬──────────────┐         │
│ │ 슬롯       │ 모델                    │ 상태          │         │
│ ├───────────┼─────────────────────────┼──────────────┤         │
│ │ default   │ openai_small_v3 (1536)  │ ✅ 활성       │         │
│ │ shadow    │ bge_m3 (1024)           │ ⏳ 인덱싱중   │         │
│ └───────────┴─────────────────────────┴──────────────┘         │
│                                                                 │
│ 듀얼 인덱싱 진행:  ▓▓▓▓▓▓▓░░░  3,200 / 5,000 청크 (64%)        │
│ 예상 완료: 약 1시간 후                                           │
│                                                                 │
│ [일시정지] [작업 로그 보기]                                       │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│ 체크포인트 진행                                                  │
│                                                                 │
│ ✅ Check 1: MVP 임베딩 모델 확정      (2026-06-01, 승인: admin) │
│ ✅ Check 2: 전환 필요성 판단          (2026-08-15, 승인: admin) │
│ ✅ Check 3: BGE-M3 인프라 검증        (2026-08-22, 승인: admin) │
│ ⏳ Check 4: 듀얼 인덱싱 시작          (진행 중...)              │
│ ⬜ Check 5: A/B 품질 비교             (대기)                    │
│ ⬜ Check 6: Canary Rollout            (대기)                    │
│ ⬜ Check 7: OpenAI 제거               (대기)                    │
│                                                                 │
│ [다음 체크포인트 확인]                                            │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 체크포인트 승인 모달 (Check 4 예시)

```
┌─────────────────────────────────────────────────────┐
│  Check 4: 듀얼 인덱싱 시작                          │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ⚠️ 이 작업은 운영 트래픽에 영향을 줄 수 있습니다.   │
│                                                     │
│  현재 KB 청크 수:           5,000 개                │
│  추정 소요 시간:            2~4시간                  │
│  예상 디스크 추가 사용:     ~30 MB                  │
│  운영 영향:                 없음 (백그라운드)        │
│                                                     │
│  체크리스트:                                        │
│  ☑ 현재 KB 청크 수 확인                            │
│  ☑ 추정 시간 검토                                  │
│  ☐ 백그라운드 작업이 운영에 영향 없음 확인          │
│  ☐ 작업 중단 가능 여부 확인                        │
│                                                     │
│  롤백 방법:                                         │
│    [일시정지] 버튼 클릭 → 즉시 중단됨               │
│    데이터 영향 없음 (검색은 OpenAI 사용 중)         │
│                                                     │
│  비고 (선택):                                       │
│  ┌───────────────────────────────────────────┐    │
│  │                                           │    │
│  └───────────────────────────────────────────┘    │
│                                                     │
│  [취소]                          [승인하고 시작]    │
└─────────────────────────────────────────────────────┘
```

### 3.3 자동 알림 (이메일 또는 Slack)

각 체크포인트가 **사용자 승인이 필요한 상태**가 되면 자동 알림:

```
[medical-compliance-tester] 🟡 임베딩 마이그레이션: Check 5 승인 대기

단계 4(Shadow A/B 평가)가 완료되었습니다.
2주간의 측정 결과를 검토하고 다음 단계 진행 여부를 결정해 주세요.

측정 결과 요약:
  • Top-5 Jaccard: 73% ✅
  • MRR@5: BGE 0.81 / OpenAI 0.78 ✅
  • 응급 청크 회상률: 97% ✅
  • 평균 지연: +180ms ✅
  • 의사 blind review: BGE 승률 52% ✅

→ 5/5 지표 통과. Check 6 진행 권장.

승인하기: https://medical-compliance-tester.run.app/settings.html#rag-migration
```

---

## 4. 사용자가 항상 통제권을 갖도록 하는 안전장치

### 4.1 절대 자동 진행하지 않는 작업
- 단계 1→2, 2→3, 3→4, 4→5, 5→6 **모든 전환은 명시적 승인 필요**
- 단계 5 내부 (10%→30%→50%→100%)도 **각 비율 증가마다 별도 승인**

### 4.2 자동 진행하는 작업 (안전)
- 단계 5에서 자동 롤백 (긴급 상황만)
- 자동 롤백은 항상 **이전 안전 상태**로만 이동 (앞으로 절대 안 감)

### 4.3 비상 차단 ("Kill Switch")
설정 페이지 상단에 **항상 표시되는 빨간 버튼**:

```
[🚨 모든 마이그레이션 즉시 중단]
  → 클릭 시: 모든 트래픽을 즉시 OpenAI(primary)로 되돌림
              듀얼 인덱싱 작업 일시정지
              사용자에게 사유 입력 요청
```

### 4.4 모든 변경 사항 감사 추적
- `embedding_migration_log` 테이블에 **누가, 언제, 어떤 결정**을 했는지 영구 기록
- `embedding_providers.last_changed_by` 필드로 마지막 변경자 추적

---

## 5. Phase 1 MVP 코드 영향 (지금부터 준비할 것)

마이그레이션을 위해 **Phase 1부터 미리** 해 둬야 할 일:

| 작업 | 이유 | Phase 1 포함? |
|------|------|--------------|
| `embedding_provider.py` 추상 클래스 작성 | 나중에 BGEM3Provider 추가만 하면 됨 | ✅ **필수** |
| `kb_chunks` 테이블에 `embedding_primary` / `embedding_secondary` 컬럼 둘 다 생성 | 마이그레이션 시 ALTER TABLE 안 해도 됨 | ✅ **필수** |
| `embedding_primary_model` 컬럼에 항상 모델 ID 기록 | 미래의 차원 충돌 방지 | ✅ **필수** |
| `embedding_providers` 테이블 생성 | 슬롯 라우팅 인프라 | ✅ **필수** |
| `embedding_migration_log` 테이블 생성 | 감사 추적 | ⏸️ Phase 4까지 미뤄도 됨 |
| BGE-M3 컨테이너 빌드 | Check 2 통과 후에 필요 | ⏸️ Phase 4 |
| 마이그레이션 UI | Check 2 통과 후에 필요 | ⏸️ Phase 4 |

→ Phase 1에 추가 작업량: **약 1~2일** (Dockerfile, 추상 클래스, 테이블 구조 1~2개)

이걸 안 해 두면 나중에 마이그레이션 시 **모든 청크의 데이터 모델을 다시 설계해야** 합니다. 비용으로 환산하면 Phase 1에 1일 투자 = 미래에 1주일 절약.

---

## 6. 확정 사항 (2026-05-27 결정 완료)

| 결정 사항 | 확정 값 | 의미 |
|----------|---------|------|
| **Phase 1 임베딩 모델** | ✅ **OpenAI text-embedding-3-small (1536차원)** | API 호출만으로 0일차 시작. 마이그레이션 시 차원 변경(1536→1024) 필요. |
| **Phase 1에 마이그레이션 인프라 미리 구축?** | ✅ **YES** | `embedding_provider.py` + duals 컬럼 + `embedding_providers` 테이블을 Phase 1에 함께 작성. |
| **체크포인트 승인 권한** | ✅ **Admin만** | Check 1~7 모든 체크포인트 승인 버튼은 `role='admin'` 사용자에게만 노출. 의사 reviewer는 품질 평가 데이터 입력만 가능. |
| **자동 알림 채널** | ✅ **이메일** | 체크포인트 승인 대기·자동 롤백 발생 시 등록된 Admin 이메일로 발송. SMTP 설정 또는 SendGrid 등 외부 서비스 연동 필요. |
| **자동 롤백 트리거 임계값** | ✅ **표준 (권장값 그대로)** | • 5분간 BGE-M3 에러율 > 1%<br>• 평균 지연이 OpenAI 대비 +500ms 초과<br>• 의사 reviewer 'wrong_info' 신고 5건 이상 |

### 6.1 권한 구현 세부
- `proxy_server.py`의 `PERMISSION_CATALOG`에 신규 권한 추가 없음 — 기존 Admin 체크 재사용
- 체크포인트 API 엔드포인트 예시: `POST /api/rag/embedding/checkpoint/{check_id}/approve` → Admin 토큰만 허용
- UI는 비-Admin에게는 진행 상황만 보이고 [승인] 버튼 자체가 렌더링되지 않음

### 6.2 이메일 알림 구현 세부
- 신규 설정 위치: `settings.html` → "RAG 설정" 탭 → "이메일 알림" 서브 섹션
  - 수신자 목록 (여러 Admin 등록 가능)
  - 알림 종류 토글 (체크포인트 대기 / 자동 롤백 / 일일 요약)
- 전송 방식 결정 필요 (Phase 1 작업 분해 시):
  - 옵션 A: SMTP 직접 (Cloud Run에서 OUTBOUND SMTP 차단 가능성 있음 → VPC NAT 통과 확인 필요)
  - 옵션 B: SendGrid / Mailgun 등 외부 API (추천 — 신뢰성 높음)
  - 옵션 C: Gmail API (구글 계정 OAuth)
- 알림 큐 테이블 신규:
  ```sql
  CREATE TABLE email_notifications (
      id TEXT PRIMARY KEY,
      recipient TEXT NOT NULL,
      subject TEXT NOT NULL,
      body_html TEXT NOT NULL,
      category TEXT,                  -- 'checkpoint_wait' | 'auto_rollback' | 'daily_summary'
      status TEXT DEFAULT 'pending',  -- 'pending' | 'sent' | 'failed'
      sent_at TEXT,
      error_message TEXT,
      created_at TEXT NOT NULL
  );
  ```

### 6.3 자동 롤백 임계값 (표준) 적용 위치
- 모니터링: `rag_queries` 테이블의 최근 5분간 행을 주기 집계 (1분 주기 cron 또는 인라인)
- 트리거 발동 시:
  1. `embedding_providers.rollout_percentage = 0` 즉시 변경
  2. `embedding_migration_log`에 `to_state='rollback'` 행 INSERT
  3. Admin 이메일 발송 (제목: `🚨 [긴급] BGE-M3 자동 롤백 발생`)
  4. UI 상단에 빨간 배너 표시 (Admin 로그인 시)

---

## 7. 다음 단계

이 전략에 동의하시면:

1. **`rag_architecture.md` 업데이트**: 섹션 3.3에 "OpenAI small (MVP) → BGE-M3 (Phase 4) 마이그레이션 가능 구조" 명시 + 본 문서 링크
2. **Phase 1 작업 분해표 작성**: 위 ✅ 항목들을 Phase 1 태스크에 포함
3. **체크포인트 1 (MVP 시작)**의 사전 준비 항목 진행

수정이나 추가 의견 있으면 말씀해 주세요. 특정 체크포인트의 기준을 더 엄격/완화하거나, 단계를 추가/삭제하는 것 모두 가능합니다.
