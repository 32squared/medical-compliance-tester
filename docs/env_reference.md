# 환경변수 전체 레퍼런스

> **4-E repo 분리 시 주의**: 이 파일은 호스트(proxy_server)와 RAG 서비스(rag_server) 두 서비스의 env를 한 곳에 정리한 단일-레포 과도기 문서입니다.
> 4-E(저장소 분리) 완료 후 **"호스트 전용" 행은 호스트 repo README**로, **"RAG 서비스 전용" 행은 RAG repo README**로 각각 이동하세요.

---

## 1. 공통/DB 연결 (`db.py`, `migrations/`)

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-*.ps1) |
|---|---|---|---|---|
| `DATABASE_URL` | `""` (빈 문자열) | PostgreSQL 연결 URL 전체. 설정 시 SQLite 무시 | `dbcommon.py:35`, 모든 migration 스크립트 | deploy.ps1, deploy-dev.ps1 `--set-env-vars`로 조합 주입; deploy-job.ps1, deploy-migrate.ps1 동일 |
| `DB_PASSWORD` | `""` | PostgreSQL 비밀번호. DATABASE_URL 미설정 시 DB_USER/DB_NAME/DB_HOST와 조합해 URL 자동 생성 | `dbcommon.py:40`, migration 스크립트 | deploy-dev.ps1 `--set-secrets db-password:latest` (Secret Manager) |
| `DB_USER` | `"app_user"` | PostgreSQL 사용자명 | `dbcommon.py:41`, migration 스크립트 | 하드코딩(deploy.ps1 URL에 포함) |
| `DB_NAME` | `"medical_app"` | PostgreSQL DB명 | `dbcommon.py:42`, migration 스크립트 | deploy.ps1 URL에 포함; DEV는 `medical_app_dev` |
| `DB_HOST` | `""` | PostgreSQL 호스트 또는 Cloud SQL Unix 소켓 경로 | `dbcommon.py:43`, migration 스크립트 | deploy.ps1 URL 내 `?host=/cloudsql/…` |
| `DB_PATH` | `"<스크립트 디렉터리>/app.db"` | SQLite DB 파일 경로 (로컬 개발/SQLite 모드 전용) | `dbcommon.py:34` | 주입 없음 (로컬 전용) |

---

## 2. 호스트 서비스 (`proxy_server.py`, `rag_routes.py`)

> 4-E 분리 후 이 섹션은 **호스트 repo README**로 이동합니다.

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-*.ps1) |
|---|---|---|---|---|
| `PORT` | `9000` (로컬) / `8080` (Cloud Run) | HTTP 수신 포트. Cloud Run은 자동 주입 | `proxy_server.py:7724`, `entrypoint.sh` | Cloud Run 자동 주입 (설정 금지) |
| `RAG_ENABLED` | `"false"` | RAG 피처 플래그. **레거시 주의**: 실제 게이트는 `RAG_SERVICE_URL` 설정 여부. RAG_ENABLED=true여도 RAG_SERVICE_URL 미설정이면 in-process 경로 유지 | `proxy_server.py:40`, `rag_routes.py:24` | deploy-dev.ps1 `--set-env-vars RAG_ENABLED=true` |
| `RAG_SERVICE_URL` | `""` | **실질 게이트**: 설정 시 `/api/rag/*` 를 이 URL로 리버스 프록시. 미설정이면 in-process 경로(RagRoutesMixin) 사용 | `proxy_server.py:47` | deploy-dev.ps1 `-RagServiceUrl` 파라미터로 조건부 주입 |
| `RAG_TRUST_SECRET` | `""` | RAG 서비스 호출 시 `X-Rag-Trust` 헤더 값. 미설정 시 네트워크 경계만으로 보호 | `proxy_server.py:48` | deploy-dev.ps1 `-RagTrustSecret` 파라미터로 조건부 주입 |
| `RAG_REQUEST_TIMEOUT` | `900` | RAG 서비스 urlopen 전체 타임아웃(초). batch_eval_rag와 동일 env명 | `proxy_server.py:53` | 미주입(기본값 사용); 필요 시 `--set-env-vars` 추가 |
| `RAG_STREAM_IDLE_TIMEOUT` | `180` | SSE 스트리밍 소켓 idle 타임아웃(초) | `proxy_server.py:54` | 미주입(기본값 사용) |
| `OPENAI_API_BASE` | `"https://api.openai.com"` | OpenAI API 엔드포인트. 프록시/테스트 환경 대체용 | `proxy_server.py:58`, `rag_legal_eval.py:32`, `rag_consultation_eval.py:33`, `medical_classifier.py:30` | 미주입(공식 엔드포인트 사용); 우회 시 `--set-env-vars` 추가 |
| `OPENAI_API_KEY` | 없음 (필수) | OpenAI API 키 | `proxy_server.py` (평가 호출), `llm_router.py:130`, `embedding_provider.py:65` | deploy-dev.ps1 `--set-secrets openai-api-key:latest` |
| `GCP_PROJECT` | `"medical-compliance-tester"` | GCP 프로젝트 ID. Cloud Run Job 트리거에 사용 | `proxy_server.py:4028` | 미주입(기본값 사용) |
| `GCP_REGION` | `"asia-northeast3"` | GCP 리전. Cloud Run Job 트리거에 사용 | `proxy_server.py:4029` | 미주입(기본값 사용) |
| `BATCH_JOB_NAME` | `"batch-runner"` | Cloud Run Job 이름. 배치 트리거 시 사용 | `proxy_server.py:4030` | 미주입(기본값 사용) |

---

## 3. RAG 서비스 (`rag_server.py`, `rag_engine.py`, `llm_router.py`, `embedding_provider.py`, `config.py`)

> 4-E 분리 후 이 섹션은 **RAG repo README**로 이동합니다.

### 3-A. rag_server.py (기동/인증)

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-*.ps1) |
|---|---|---|---|---|
| `RAG_TRUST_SECRET` | `""` | 수신 측 `X-Rag-Trust` 헤더 검증 시크릿. 미설정 시 신뢰헤더 검증 생략 | `rag_server.py:40` | deploy-rag.ps1 `--set-secrets` (미작성 시 미주입) |
| `RAG_ALLOW_SQLITE` | `""` (빈 문자열 = 차단) | DATABASE_URL 미설정 시 SQLite 모드 허용 여부. **Cloud Run 배포에서는 절대 설정 금지** (DB 손상 위험) | `rag_server.py:221` | 미주입(로컬 개발 전용 — `RAG_ALLOW_SQLITE=1`) |
| `K_REVISION` | `"local"` | Cloud Run 자동 주입 리비전명. `/health` 응답의 `version` 필드에 노출 | `rag_server.py:144` | Cloud Run 자동 주입 |
| `DATABASE_URL` | `""` | PostgreSQL 연결 URL (섹션 1과 동일) | `rag_server.py:220` | deploy-rag.ps1 `--set-env-vars` 또는 `--set-secrets` |

### 3-B. llm_router.py (LLM 호출)

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-*.ps1) |
|---|---|---|---|---|
| `RAG_LLM_MODEL` | `"gpt-5.4-mini"` | RAG 응답 생성 메인 모델 | `llm_router.py:129` | deploy-dev.ps1 `--set-env-vars RAG_LLM_MODEL=gpt-5.4-mini` |
| `RAG_LLM_FALLBACK_MODEL` | `"gpt-5.4-mini"` | 재생성(retry) 시 사용 모델 | `llm_router.py:277` | deploy-dev.ps1 `--set-env-vars RAG_LLM_FALLBACK_MODEL=gpt-5.4-mini` |
| `RAG_LLM_DEFAULT_PROVIDER` | `"openai_gpt5"` | LLM 프로바이더 슬롯 선택 | `llm_router.py:258` | 미주입(기본값 사용) |
| `LLM_REASONING_EFFORT` | `"low"` | GPT-5 계열 reasoning_effort 파라미터 (`none`/`low`/`medium`/`high`/`xhigh`). 대화형은 `none` 권장(TTFT 단축) | `llm_router.py:195` | deploy-dev.ps1 `--set-env-vars LLM_REASONING_EFFORT=low` |
| `OPENAI_API_KEY` | 없음 (필수) | OpenAI API 키 | `llm_router.py:130` | 섹션 2와 동일 (공유 Secret) |

### 3-C. embedding_provider.py / config.py (임베딩)

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-*.ps1) |
|---|---|---|---|---|
| `RAG_EMBEDDING_MODEL` | `"text-embedding-3-small"` | 임베딩 모델명 | `embedding_provider.py:68`, `config.py:244` | 미주입(기본값 사용) |
| `RAG_EMBEDDING_PROVIDER_DEFAULT` | `"openai"` | 기본 임베딩 프로바이더 (`openai` 또는 `bge_m3`). DB(embedding_providers 테이블) 미구성 시 폴백 | `embedding_provider.py:193`, `config.py:239` | 미주입(기본값 사용) |
| `RAG_EMBEDDING_PROVIDER_{SLOT}` | `""` | 슬롯별 프로바이더 재정의 (`SLOT`=`DEFAULT`/`INGEST`/`SHADOW`). 비어있으면 `RAG_EMBEDDING_PROVIDER_DEFAULT` 사용 | `embedding_provider.py:192` | 미주입 |
| `BGE_M3_URL` | `""` | 자체호스팅 BGE-M3 서비스 URL (Phase 4+ 전용, 현재 미구현) | `embedding_provider.py:151` | 미주입 |

### 3-D. rag_engine.py (Retrieval Gate 임계값)

모든 GATE 변수는 기본값이 **shadow mode**(로깅만, 블로킹 없음) 기준입니다.
`RETRIEVAL_GATE_ENFORCE=true`로 설정하면 INSUFFICIENT 판정 시 LLM 호출을 스킵합니다.

| 변수명 | 기본값 | 설명 | 사용처 (파일) |
|---|---|---|---|
| `RETRIEVAL_GATE_ENFORCE` | `"false"` | `true`로 설정 시 게이트 강제 적용(INSUFFICIENT → 템플릿 반환) | `rag_engine.py:44` |
| `GATE_TOP1_PASS` | `0.55` | Top-1 청크 cosine 점수 합격 임계값 | `rag_engine.py:45` |
| `GATE_TOP1_WEAK` | `0.42` | Top-1 청크 cosine 점수 약합격 임계값 (보조 조건 추가 검사) | `rag_engine.py:46` |
| `GATE_CHUNK_COUNT_PASS` | `3` | 합격 기준 최소 청크 수 | `rag_engine.py:47` |
| `GATE_TOPIC_MATCH_PASS` | `2` | 합격 기준 최소 topic 일치 청크 수 | `rag_engine.py:48` |
| `GATE_WEIGHTED_PASS` | `2.0` | 가중 점수 합격 임계값 | `rag_engine.py:49` |
| `GATE_TOPIC_THRESHOLD` | `0.30` | 일반 topic 유사도 임계값 | `rag_engine.py:50` |
| `GATE_TOPIC_ALIGNMENT_THRESHOLD` | `0.30` | evidence_topic 라벨 청크 전용 topic 정렬 임계값 (미라벨링 청크는 자동 통과) | `rag_engine.py:52` |
| `GATE_RELEVANT_COSINE` | `0.42` | 관련 청크 판정 cosine 임계값 | `rag_engine.py:53` |
| `ENABLE_EVIDENCE_TOPIC_CHECK` | `"true"` | evidence_topic 정렬 검증 활성화. `false`로 설정 시 해당 검증 완전 비활성화(디버그/우회 전용) | `rag_engine.py:58` |
| `RAG_HYBRID_WEIGHTED` | `"0"` | `"1"` 설정 시 Source Priority 가중 reranker 활성화(RRF 후 적용) | `rag_engine.py:814` |
| `RAG_GUARDRAIL_FP_FILTER` | `"true"` | 가드레일 FP 필터 활성화. `false`/`0`/`no`/`off`로 비활성화 가능 | `rag_engine.py:1735` |

> 배포 주입: 위 GATE 변수들은 deploy-rag.ps1에 현재 명시적 주입이 없습니다(기본값 사용).
> 임계값 튜닝이 필요한 경우 `--set-env-vars`로 개별 추가하세요.

---

## 4. 배치 평가 (`batch_eval_rag.py`, `job_runner.py`)

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-job.ps1) |
|---|---|---|---|---|
| `RAG_SERVICE_URL` | `""` (P1부터 필수) | RAG 생성 엔드포인트. 미설정 시 배치 실행 거부 | `batch_eval_rag.py:32` | deploy-job.ps1의 `$EnvSpec`에 추가 필요 |
| `RAG_TRUST_SECRET` | `""` | RAG 서비스 호출 신뢰 시크릿 | `batch_eval_rag.py:33` | deploy-job.ps1 `--set-secrets` 추가 필요 |
| `RAG_REQUEST_TIMEOUT` | `900` | RAG HTTP 요청 전체 타임아웃(초) | `batch_eval_rag.py:34` | 미주입(기본값 사용) |
| `RAG_LEGAL_EVAL` | `"1"` | `"0"` 시 RAG 전용 법률 평가기 대신 라이브 `_evaluate_gpt` 폴백 | `batch_eval_rag.py:82` | 미주입(기본값 활성) |
| `RAG_CONSULT_EVAL` | `"1"` | `"0"` 시 RAG 전용 문진 평가기 대신 라이브 `_evaluate_consultation` 폴백 | `batch_eval_rag.py:93` | 미주입(기본값 활성) |
| `BATCH_WORKERS` | `8` | 병렬 배치 워커 수 | `batch_eval_rag.py:491` | 미주입(기본값 사용) |
| `EVAL_MODEL` | `"gpt-4o-mini"` | 평가에 사용할 GPT 모델명 | `batch_eval_rag.py:500` | 미주입(기본값 사용) |
| `OPENAI_API_KEY` | 없음 (필수) | OpenAI API 키 | `batch_eval_rag.py:496` | deploy-kb-seed.ps1 `--set-secrets openai-api-key:latest` 참조 |
| `DIAG_LOG` | `""` | `"1"` 시 both_A=false 케이스 진단 로그 출력 | `batch_eval_rag.py:343` | 미주입(디버그 전용) |
| `EVAL_EMIT_JSONL` | `"1"` | `"0"` 시 JSONL 결과 파일 출력 생략 | `batch_eval_rag.py:603` | 미주입(기본값 활성) |
| `RUN_ID` | `""` (필수) | Cloud Run Job 실행 ID (job_runner.py 필수) | `job_runner.py:130` | deploy-job.ps1 execution override 주입 |
| `SCENARIO_IDS_JSON` | `""` (RUN_ID 없으면 필수) | 실행할 시나리오 ID JSON 배열 | `job_runner.py:63` | deploy-job.ps1 execution override 주입 |
| `JOB_PAYLOAD_ID` | `""` | DB payload 방식 대용량 배치 ID (SCENARIO_IDS_JSON 대체) | `job_runner.py:50` | execution override |
| `RUN_BY` | `"job-runner"` | 실행 주체 식별자 (이력 기록용) | `job_runner.py:134` | execution override |
| `LABEL` | `""` | 실행 레이블 (이력 기록용) | `job_runner.py:135` | execution override |
| `FLUSH_EVERY` | `5` | DB flush 간격 (완료 시나리오 수) | `job_runner.py:136` | 미주입(기본값 사용) |

---

## 5. 마이그레이션 (`migrations/migrate_runner.py`, `migrations/run_migration_*.py`)

| 변수명 | 기본값 | 설명 | 사용처 (파일) | 배포 주입 (deploy-migrate.ps1) |
|---|---|---|---|---|
| `DATABASE_URL` | `""` | PostgreSQL 연결 URL (섹션 1과 동일) | `migrations/migrate_runner.py:237`, 모든 `run_migration_*.py` | deploy-migrate.ps1 `$EnvSpec`에 포함 |
| `DB_PASSWORD` | `""` | PostgreSQL 비밀번호 (섹션 1과 동일) | `migrations/run_migration_*.py` | deploy-migrate.ps1 URL에 포함 |
| `DB_USER` | `"app_user"` | PostgreSQL 사용자명 (섹션 1과 동일) | `migrations/run_migration_*.py` | deploy-migrate.ps1 URL에 포함 |
| `DB_NAME` | `"medical_app"` | PostgreSQL DB명 (섹션 1과 동일) | `migrations/run_migration_*.py` | deploy-migrate.ps1 `-DbName` 파라미터로 제어 |
| `DB_HOST` | `""` | PostgreSQL 호스트 (섹션 1과 동일) | `migrations/run_migration_*.py` | deploy-migrate.ps1 URL에 포함 |
| `RUN_MODE` | `""` | `"migrate"` 설정 시 entrypoint.sh가 `migrate_runner.py --sync` 실행 | `entrypoint.sh` 분기 (migrate_runner.py) | deploy-migrate.ps1 `$EnvSpec`에 `RUN_MODE=migrate` 포함 |

---

## 6. 기타 런타임 / Cloud Run 플랫폼 변수

| 변수명 | 기본값 | 설명 | 사용처 (파일) |
|---|---|---|---|
| `RUN_MODE` | `""` | `"job"` → `job_runner.py`, `"migrate"` → `migrate_runner.py`, 그 외 → `proxy_server.py` | `entrypoint.sh` |
| `DATA_DIR` | `<스크립트 디렉터리>` | 데이터 파일(guidelines.json 등) 탐색 기준 디렉터리 | `config.py:9`, `guideline_loader.py:13` |
| `APP_ENV` | `""` | 애플리케이션 환경 구분 레이블 (`development` 등, 로깅/표시 전용) | deploy-dev.ps1 `--set-env-vars APP_ENV=development` |

---

## 수집 커버리지 요약

| 서비스 그룹 | env 변수 수 |
|---|---|
| 공통/DB 연결 | 6 |
| 호스트 (proxy_server) | 11 |
| RAG 서비스 (rag_server/rag_engine/llm_router/embedding_provider) | 20 |
| 배치 (batch_eval_rag/job_runner) | 15 |
| 마이그레이션 (migrate_runner) | 6 (공통 5개 + RUN_MODE) |
| 기타 런타임 | 3 |
| **합계** | **61** |

> grep 수집 기준: 루트 `*.py` 전체 `os.environ.get(...)` / `os.environ[...]` 패턴 전수 조회 + entrypoint.sh RUN_MODE 분기 + deploy-*.ps1 4종 `--set-env-vars`/`--set-secrets` 목록.
> 스크립트 전용(`scripts/*.py`) 운영 무관 변수(`ADMIN_PW`, `ANALYZE_RUN_ID`, `VERIFY_SCENARIO_ID`, `OUT_GCS_PATH`, `DUMP_RUN_ID` 등)는 운영 서비스와 무관한 개발·분석 도구이므로 이 표에서 제외했습니다.

---

## 부록: 네트워크 egress 경로 실측 (4-C/C-4, 2026-06-10)

| 항목 | 값 |
|---|---|
| VPC 라우터 / NAT | `medical-router` / `medical-nat` (asia-northeast3, MANUAL_ONLY=고정 IP, ALL_SUBNETWORKS) |
| 호스트 dev egress | `all-traffic` + medical-connector → **모든 외부 API(SKIX/OpenAI)가 NAT 고정 IP 경유** |
| RAG dev egress | `private-ranges-only` + medical-connector → 사설 대역(Cloud SQL)만 VPC, **OpenAI는 Cloud Run 직접 egress(NAT 미경유, 비고정 IP)** |
| 서비스 계정 | 양쪽 모두 default compute SA(716262961556-compute@) — **C-3에서 전용 SA 분리 예정** |

- 함의: RAG의 OpenAI 호출은 고정 IP가 아니다. OpenAI는 IP 허용목록이 불필요하므로 현 구성 유지. 외부 API에 IP 제한이 생기면 RAG egress를 all-traffic으로 변경해야 한다.
- IAM 인증 전환(C-3)은 egress 경로와 무관(인그레스 정책) — 상호 영향 없음 확인.
- 롤백(1커맨드): `gcloud run services update medical-rag-dev --region=asia-northeast3 --allow-unauthenticated`
