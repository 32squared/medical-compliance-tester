# [확인 요청] Cloud SQL pgvector 활성화 가능 여부

**발신**: medical-compliance-tester 개발팀
**수신**: 인프라/DevOps 담당자
**일자**: 2026-05-27
**프로젝트**: medical-compliance-tester (Cloud Run + Cloud SQL)
**시급도**: 일반 (1주 이내 회신 요청)
**연관 문서**: [Phase 1 작업 분해표](./phase1_task_breakdown.md), [RAG 아키텍처](./rag_architecture.md)

---

## 배경

의료법 준수 테스트 도구의 RAG(Retrieval-Augmented Generation) 시스템 구축을 위해 현재 Cloud SQL PostgreSQL 인스턴스에 **pgvector extension** 활성화가 필요합니다.

pgvector는 벡터 검색용 PostgreSQL extension으로, 의료 지식 문서의 임베딩 벡터를 저장·검색하기 위한 표준 도구입니다. 별도 벡터 DB(Pinecone/Qdrant 등) 도입 없이 기존 Cloud SQL을 그대로 활용하는 것이 목표입니다.

---

## 확인 부탁드리는 4가지 항목

### 1. PostgreSQL 버전
- 현재 Cloud SQL 인스턴스의 PostgreSQL major 버전은?
- pgvector 0.5+ 권장 (HNSW 인덱스 지원). **PostgreSQL 14 이상 권장**, 11~13도 동작 가능.

### 2. `cloudsql.enable_pgvector` flag 활성화 권한
- 현재 인스턴스에 이 flag가 이미 활성화되어 있는지?
- 아니라면 활성화 변경 권한 보유자는 누구인지? (Cloud SQL Admin 권한 필요)
- 활성화 시 인스턴스 재시작 필요 — **다운타임 가능한 시간대** 안내 부탁드립니다.

### 3. 인스턴스 사양 (현재 + 향후 여유)
- 현재 vCPU / RAM은?
- 예상 부하:
  - Phase 1 MVP: 약 5,000 벡터 청크 (~30MB) — 어떤 사양이든 가능
  - 6개월 후: 50,000 청크 (~300MB) — **db-g1-small (1.7GB RAM) 이상 권장**
  - 1년 후: 500,000 청크 (~3GB) — db-custom (4vCPU/8GB) 검토
- 현재 사양에서 시작 가능한지, 사전에 업스케일 필요한지 판단 부탁드립니다.

### 4. DB 사용자 권한
- `CREATE EXTENSION vector;` 실행 가능한 superuser 권한 보유자는 누구인지?
- 또는 Cloud SQL의 `cloudsqlsuperuser` 역할로 실행해야 하는지?

---

## 활성화 후 실행할 명령 (참고용)

확인 완료되면 마이그레이션 스크립트에서 다음 명령을 실행합니다:

```sql
-- 1. extension 활성화
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;  -- BM25 보조용

-- 2. 벡터 컬럼 + HNSW 인덱스 생성 (kb_chunks 테이블)
CREATE INDEX idx_kb_chunks_emb_primary ON kb_chunks
    USING hnsw (embedding_primary vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 3. 동작 확인
SELECT '[1,2,3]'::vector;  -- 결과: [1,2,3]
```

---

## 영향 범위

- **활성화 시 다른 서비스 영향**: 없음 (extension 추가만, 기존 테이블·쿼리 변경 없음)
- **롤백 방법**: `DROP EXTENSION vector;` 1줄 (extension 제거 시 관련 컬럼·인덱스도 자동 삭제)
- **추가 비용**: extension 자체는 무료. 벡터 데이터 저장으로 인한 디스크 사용량만 증가 (MVP 기준 ~30MB)

---

## 회신 부탁드리는 형식

```
1. PostgreSQL 버전: ______
2. pgvector flag 활성화 여부: [ ] 이미 활성화 / [ ] 비활성화
   - 비활성화 시 활성화 가능 여부: [ ] 가능 / [ ] 불가 / [ ] 검토 필요
   - 권한 보유자: ______
   - 가능 다운타임: ______
3. 인스턴스 사양: vCPU ___ / RAM ___ GB
   - 업스케일 필요 여부: [ ] 현재 OK / [ ] 업스케일 권장 / [ ] 업스케일 필수
4. CREATE EXTENSION 실행 권한자: ______
```

---

**막히면 RAG 시스템(Phase 1) 전체가 시작 불가**합니다. 1주 이내 회신 부탁드립니다.

확인이 필요한 사항이 있으면 언제든 답신 주세요.

감사합니다.
