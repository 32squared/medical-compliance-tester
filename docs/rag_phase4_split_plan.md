# Phase 4 — RAG 완전 저장소 분리 작업 계획

> 전수조사(2026-06-10, 9-에이전트: 6영역 조사 + 3렌즈 누락검증) 기반의 실행 계획.
> 상위 로드맵: [rag_separation_plan.md](rag_separation_plan.md) (Phase 0~3 완료 상태 참조)

---

## 0. 조사 결론 요약 — 분리 난이도는 "낮음", 단 정리할 결합 5개

**좋은 소식 (디커플링 대부분 완료):**
- RAG의 호스트 테이블 접근은 **단 2곳**: `rag_routes.py:218` conversations INSERT(감사기록, ON CONFLICT DO NOTHING), `batch_eval_rag.py:122` scenarios READ(scenarios.json 폴백 보유). settings(API 키) 접근 **없음** — 전부 환경변수.
- 데이터 렌즈 누락검증: **숨은 데이터 결합 0건** (FK 전부 RAG 테이블 상호참조, 파일/GCS/캐시 공유 없음).
- `migrations/` 001~009 가 **전부 RAG DDL** → 디렉터리 통째로 신규 repo 이동 가능. 호스트 스키마는 db.py init_db 가 자체 관리(Phase 0 분리 완료).
- Dockerfile 멀티모드(RUN_MODE), deploy-rag.ps1, 마이그레이션 러너, 신뢰헤더 인증 모두 구축·dev 실증 완료.

**분리 전 정리가 필요한 결합 (전수조사 발견):**
| # | 결합 | 위치 | 심각도 |
|---|---|---|---|
| C1 | batch_eval_rag → proxy_server 평가함수 import + `ProxyHandler._add_log` monkey-patch + 실패 시 자체 평가기로 **무음 폴백** | batch_eval_rag.py:29-60, 288-315 | 높음 |
| C2 | 호스트 in-process 모드: proxy_server 가 RagRoutesMixin 상속(:32, :1805) — repo 분리 시 import 불가 | proxy_server.py | 높음 |
| C3 | 서비스 간 인증 미흡: 양쪽 `--allow-unauthenticated` + RAG_TRUST_SECRET 미설정(네트워크 경계 의존) | deploy-*.ps1 | 높음 |
| C4 | prod baseline 미실행: prod DB 에 schema_migrations/RAG DDL 채택 안 됨 | 운영 DB | 높음(선결) |
| C5 | 공유 코드 물리 미분리: dbcommon + compliance-rules(analyzer/config/guideline_loader/consultation_loader + JSON 3종) | 루트 | 구조적 |

**불변 조건 (이 계획의 전제):**
- **SSE/프론트는 same-origin 리버스 프록시 영구 유지.** 프론트(chat_tester/kb_manager)는 SSE 이벤트 포맷·`/api/rag/*` 경로에 암묵 의존 — RAG 서비스를 브라우저에 직접 노출하지 않는다(CORS/신뢰헤더 불가). 프록시 규약 = 서비스 간 공개 계약.
- 기존 평가 시스템(컴플라이언스/문진)에 영향 없음. 각 단계는 독립 배포·롤백 가능.

---

## 1. 사전 결정 사항 — ✅ **2026-06-10 사용자 확정: D1~D7 권고안 전체 채택**

| ID | 결정 | 권고안 | 대안 |
|---|---|---|---|
| D1 | 공유 코드 배포 방식 | **git submodule** — 공유 repo 1개(`medical-shared`: `dbcommon` + `compliance_rules` 패키지). 1인 팀·gcloud builds submit(로컬 업로드)과 궁합 좋음. 팀 확장 시 pip(Artifact Registry)로 승격 | pip 패키지(초기 과투자) / 벤더링(드리프트 위험) / 모노레포(분리 목표와 상충) |
| D2 | 호스트 in-process 모드 | **제거 (경로 A)** — RAG_SERVICE_URL 필수화, 미설정 시 /api/rag/* → 503 명시 응답. 로컬 dev 는 `python rag_server.py --port 9100` + RAG_SERVICE_URL=localhost 로 동일 토폴로지 재현 | 경로 B: RAG 전체를 pip 로 호스트에 설치해 폴백 유지(분리 목적 퇴색, 의존성 비대) |
| D3 | batch_eval_rag 소속 | **호스트 잔류** — 평가는 테스트 시스템의 책무. 생성만 in-process `rag_engine.generate_response` → **HTTP `/api/rag/chat`** 전환(SKIX 와 동일 규약). C1 의 monkey-patch/무음 폴백 제거 | RAG repo 이동 + 자체 평가기(rag_legal_eval/rag_consultation_eval) 사용 — 평가 기준이 호스트와 분기될 위험 |
| D4 | 신규 repo | 이름 `medical-rag-service`(가칭), **private**, 동일 GitHub 계정 | 조직 생성 등 |
| D5 | 서비스 간 인증 | **Cloud Run IAM(OIDC ID token)** — RAG 서비스 `--no-allow-unauthenticated`, 호스트 SA 에 run.invoker, _proxy_to_rag 가 메타데이터 서버에서 ID 토큰 취득·첨부. RAG_TRUST_SECRET 은 심층방어로 병행 | 공유 시크릿만(위변조 방지 불완전) |
| D6 | CI/CD | **CI 만 GitHub Actions**(py_compile + pytest(SQLite) + migrate_runner --status). 배포는 기존 PowerShell 수동 유지(현 운영 일관성) | 전체 CD 자동화(추후) |
| D7 | prod baseline 시점 | 4-D 단계에서 **별도 승인 후** 실행 (`deploy-migrate.ps1 -Prod`) | — |

부수 결정(권고 그대로 진행, 이견 시 변경):
- kb_manager.html 등 **모든 UI 는 호스트 잔류**(프록시 경유라 변경 불필요). RAG repo 는 UI 없음.
- ~~rag_legal_eval/rag_consultation_eval 은 RAG repo 이동~~ → **호스트 잔류로 정정(2026-06-10, P1 사실확인)**: 둘 다 stdlib-only 순수 평가기(RAG/호스트 모듈 import 전무)로, RAG 트랙 분리 평가 기준(v1.5.1)을 구현한 **테스트 시스템의 평가 자산**. batch_eval_rag 의 주 평가기이며 호스트 평가함수는 폴백 — 이 동작을 P1 에서 그대로 보존(비교성 유지). medical_rag_pipeline 은 RAG repo 이동 유지.
- conversations INSERT(감사기록)는 **현상 유지**(공유 DB, 충돌무해) — 수용된 부채로 문서화.
- `RAG_ENABLED` 레거시 플래그: 호스트에서 의미 재정의(문서화) 후 단계적 제거, 신규 repo 에는 미반입.

---

## 2. 작업 단계

### 4-A. 분리 전 결합 절단 — ✅ **완료 (2026-06-10, P1~P5 전체 게이트 PASS)**
> P1 C1절단(b637344) · P2 rag_server 가드/health/SIGTERM(41ddec8) · P3 격리테스트(b11edc3) ·
> P4 운영하드닝(7c14074, 103fe19) · P5 env 레퍼런스 61종(docs/env_reference.md).
> 결과: 허용 결합 1건만 잔존(proxy_server→rag_routes, 4-E 소거 대상). 실서비스 스모크
> (medical-rag-dev 대상 batch HTTP SSE 왕복) 통과.
1. **C1 절단** (P1 설계 확정 2026-06-10): batch_eval_rag 는 HOST 잔류(D3). 절단 대상 3가지만 —
   - 생성: `rag_engine.generate_response` 직접 호출 → `RAG_SERVICE_URL` 의 `/api/rag/chat` HTTP(SSE) 호출로 전환(미설정 시 명시 에러 — 무음 폴백 금지).
   - 무음 폴백 제거: proxy_server import 실패 시 None 폴백 → 명시 에러.
   - monkey-patch 제거: `ProxyHandler._add_log` 클래스 패치 → 명시 주입(log_fn 파라미터 등).
   - **평가 로직은 무변경**: rag_legal_eval/rag_consultation_eval(주) + 호스트 함수(폴백) 구성 그대로 — 셋 다 HOST 소속이 되므로 import 적법. 비교성 100% 보존.
   - 검사기 동기화: RAG_MODULES 에서 batch_eval_rag/rag_legal_eval/rag_consultation_eval 제거, ALLOWED_COUPLINGS 항목 삭제, MAX_ALLOWED_COUPLINGS 2→1.
2. **job_runner 확인**: proxy_server 평가함수 import 는 호스트 내부 결합(잔류 파일)이므로 유지. 단 RAG 모듈 import 이 없음을 테스트로 고정.
3. **rag_server 기동 검증 강화**: RUN_MODE=rag + DATABASE_URL 미설정 시 기동 실패(명시 에러). health 응답에 `service/version/schema` 포함.
4. **운영 하드닝(저비용 묶음)**: SIGTERM graceful shutdown(rag_server/proxy_server), `[RAG-PROXY]` 등 진단 print `flush=True`, `OPENAI_API_BASE` env 도입(api.openai.com 하드코딩 제거), `RAG_REQUEST_TIMEOUT` env, env 변수 전체 README 표(게이트 임계값 10여 개 포함).
5. 검증 게이트: 기존 테스트 무회귀 + dev 배포 1회(분리 모드) + 배치평가 스모크(시나리오 2~3건).

### 4-B. 공유 패키지 사전 재배치 — ✅ **완료 (2026-06-10, B0~B5 게이트 PASS)**
> 커밋: dbcommon 패키지화(6c3c52e) · compliance_rules+config분할+resources(963db9d) ·
> 검사기+B5+facade해소(a46d4c3). 게이트 **0 fail / 0 warn**(facade WARN 3건 해소),
> 전체 pytest 신규 실패 0(HEAD 대조). config.py 분할로 SKIX 설정 유출 차단.
> 신설: [3b] json-bundle-sync(루트 vs 번들 JSON sha256) — 4-E 선결: RAG 5파일
> (rag_engine.py:61 등)의 루트 JSON 직접 읽기를 패키지 참조로 전환 후 루트 사본 제거.
1. `packages/medical_shared/` 생성: `dbcommon/`, `compliance_rules/`(analyzer, config, guideline_loader, consultation_loader + guidelines.json, violation_rules.json, consultation_checklists.json) + `pyproject.toml`.
2. JSON 로드를 `importlib.resources` 로 전환(`CHECKLISTS_PATH` 등 `__file__` 하드코딩 제거 — 패키징 후 경로 문제 선제 차단).
3. 루트에 호환 shim(`dbcommon.py` → `from packages.medical_shared.dbcommon import *`) 유지해 기존 import 무변경.
4. 검증 게이트: 전체 테스트 + dev 배포 1회. (이 단계까지는 단일 repo — 분리 실행 전 가장 위험한 변경을 먼저 소화)

### 4-C. 서비스 간 인증 하드닝 (분리 전 라이브 검증, 0.5~1일)
1. RAG 서비스 `--no-allow-unauthenticated` + 전용 서비스 계정 분리(host-sa / rag-sa / migrate-sa, 최소권한).
2. `_proxy_to_rag` 에 ID 토큰(metadata server, audience=RAG_SERVICE_URL) 첨부. RAG_TRUST_SECRET 병행 설정.
3. Cloud NAT/VPC egress 실측 확인(`gcloud compute routers nats list`) — OpenAI 호출 경로 문서화.
4. verify_rag_separation 하니스에 ID 토큰 옵션 추가.
5. 검증 게이트: dev 분리 모드 e2e(브라우저 포함) ALL PASS. 실패 시 `--allow-unauthenticated` 복귀(1커맨드 롤백).

### 4-D. prod baseline + prod 분리 모드 (승인 필요, 0.5일)
> ✅ **D-1 완료 (2026-06-11, 사용자 승인 실행)**: `db-migrate-prod-lf7kh` exit(0). 로그 확증 —
> `[sync] schema_migrations 비어있음 → baseline 채택`, `baseline done - 9 stamped`(001~009 stamp/no-exec),
> **`apply done - 0 applied`**(DDL 0건 실행 = prod 스키마 무변경, 이력 테이블 9행만 추가).
> 이로써 신규 repo `migrate_runner --sync`가 prod 에서 001~009 재실행하는 사고 위험 제거 — E-6 prod 단계 선행 게이트 해제.
1. `deploy-migrate.ps1 -Prod -Execute -Wait` → prod DB schema_migrations 채택(009 baseline). — ✅ 완료
2. prod RAG 서비스(`medical-rag`) 배포 + 호스트에 RAG_SERVICE_URL 주입(기능 게이트는 기존 플래그 유지 — 다크 론치).
3. 검증 게이트: prod 스모크(health + 인증 + chat 1회). **이 단계 전체가 사용자 승인 후 진행.**

### 4-E. 저장소 분리 실행 (1~2일)
> ✅ **E-1/E-2 완료 (2026-06-10)**: `medical-shared` main@960ec15(이력 2커밋, packages/medical_shared→루트),
> `medical-rag-service` main@b3819da(이력 84커밋+CI 배치+submodule 연결 = 86커밋). filter-repo는
> `--no-local` 클론 필수. 신규 repo 단독 검증: py_compile 80파일 0에러 + cross-import(--forbid host) OK +
> migrate_runner --status 동작 + pytest 97 passed(분리 환경에선 test_rag_conversation_state 도 통과).
> **사전 수렴(4f533f2)**: RAG 16모듈 db facade→dbcommon 직접 import, init_db→ensure_rag_schema(7곳) —
> db.py(호스트 164KB) 신규 repo 유입 차단.
> **매니페스트 정정 2건**: test_rag_kb_api(save_session=호스트 세션 함수 의존)·test_phase1_integration
> (호스트 9000 대상) → 호스트 잔류. rag ci.yml 에서 호스트 평가 테스트 2건 제거(P1 준수).
> **잔여**: ① 호스트 모노레포의 in-tree packages→submodule 전환은 E-6 검증 후(보류),
> ② medical-rag-service GitHub Actions 는 private submodule 인증 필요 — 사용자가 PAT 시크릿
> (medical-shared 읽기 권한) 추가 후 checkout `token:` 지정해야 그린(그 전까지 checkout 단계 실패).
1. GitHub: `medical-shared`(D1), `medical-rag-service`(D4) 생성. — ✅ 사용자 생성 완료(2026-06-10)
2. `git filter-repo` 로 이력 보존 이식 (✏ 2026-06-10 사전조사로 매니페스트 정정 — 진실 소스는 검사기 RAG_MODULES):
   - **신규 RAG repo 로 이동 (루트 33파일 = 검사기 RAG_MODULES)**: rag_server/routes/engine/db, llm_router, citation_verifier, embedding_provider, retrieval_router, pii_masker, medical_classifier, evidence_pack, review_queue, kb_ingest, kb_stats, kb_rag_audit, seed_*(7종), collect_public_kb, backfill_evidence_topic, medical_rag_pipeline, rag_gap_analysis, debug_rag, **verify_db_005, reembed_missing, dur_collector, reindex_korean_tsv, copy_kb_to_dev, verify_kb_health_kdca**(사전조사 보강), **migrations/ 전체**(001~009 + 러너 + test_migrate_runner), tests/ RAG 그룹(RAG-only 20종 + diagnose_rag_env/validate_rag_direct/test_rag_chat_endpoint/test_rag_kb_api/auto_validate_rag/verify_rag_separation), deploy-rag.ps1, Dockerfile(rag 고정·RUN_MODE 제거), entrypoint, .dockerignore, **.gitignore에 !__init__.py 예외 포함**, README(env 표 RAG 행 이동).
   - **호스트 잔류 (루트 15파일)**: proxy_server, db, batch_executor, job_runner, runner, **batch_eval_rag/rag_consultation_eval/rag_legal_eval**(P1 결정), dashboard, main, migrate 도구류, create_*_excel, 모든 HTML, scripts/(운영분석), 호스트 테스트(test_rlhf_*, test_guardrail_false_positives, test_rag_consultation_eval/test_rag_legal_eval 등).
   - **판단 보류 항목**: test_host_rag_isolation(분리 후 의미 소멸 — 호스트 잔류 후 제거 검토), conftest.py(양쪽 복제), test_phase1_integration(내용 확인 필요).
   - **검사기 거취**: import-boundary/mixin-contract는 분리 후 "상대 모듈 import 금지"로 단순화해 양쪽 CI 이식. json-bundle-sync는 루트 JSON 제거와 함께 삭제.
   - **medical-shared**: packages/medical_shared (4-B 산출물).
3. 호스트 repo 정리(D2 경로 A): RagRoutesMixin import/상속 제거, in-process 디스패치 4곳 제거 → RAG_SERVICE_URL 필수(미설정 시 503 + 명시 메시지), `_handle_rag_route` 제거.
4. 신규 repo CI(D6): GitHub Actions — py_compile / pytest(SQLite, DATABASE_URL 없이) / migrate_runner --status.
5. 검증 게이트: 신규 repo 에서 deploy-rag.ps1 → dev RAG 서비스 교체 → verify_rag_separation ALL PASS + 브라우저 e2e + 배치평가 스모크. 호스트 repo 단독 배포 검증(RAG 코드 없는 이미지).
> 🔄 **E-6 부분 완료 (2026-06-11)**: 신규 repo(medical-rag-service@5af8625)에서 Cloud Build →
> `medical-rag-dev-00004-fl9` 100% 서빙. **verify_rag_separation ALL PASS**(health version=00004-fl9
> schema=009 + rag_result(auth)=200 + chat SSE STOP+citations). 빌드 보강: requirements.txt(매니페스트
> 누락분), entrypoint RAG 전용화(job/service 호스트분기 제거), Dockerfile ENV RUN_MODE=rag.
> 호스트 dev 배선: RAG_SERVICE_URL 설정됨 + RAG_USE_IAM 기본 auto(Cloud Run metadata 토큰 자동) → 별도주입 불요.
> **잔여**: ① 호스트 경유 브라우저 e2e(사용자) — 직접경로는 입증, 리버스프록시 경로 최종확인,
> ② 배치 스모크(로컬 OPENAI_API_KEY/dev DB private-IP 부재로 보류 — RAG 생성/citations 는 verify 로 입증됨),
> ③ 호스트 모노레포 RAG 파일 물리 제거 + packages in-tree→submodule 전환(되돌리기 어려운 큰 변경 — 사용자 결정 후).

### 4-F. 마무리 (0.5일)
1. 문서 갱신: rag_separation_plan.md Phase 4 완료 표기, CLAUDE.md 파일구조/명령 갱신, 운영 런북(롤백 절차: 신규 repo 이전 마지막 모놀리스 이미지 태그 보존).
2. 1~2주 운영 관찰 후 잔존 죽은 코드/플래그(RAG_ENABLED 등) 제거 커밋.

**총 추정: 4.5~7 작업일** (1인, 검증 게이트 포함, 4-D 승인 대기 별도)

---

## 3. 리스크 & 완화

| 리스크 | 심각도 | 완화 |
|---|---|---|
| prod baseline 누락 상태에서 신규 repo `--sync` 실행 → 001~009 전체 적용 시도·충돌 | 높음 | 4-D 를 4-E 의 선행 게이트로 고정. migrate_runner 가 baseline 부재 감지 시 중단하도록 가드 추가 |
| batch_eval_rag 평가 경로 변경으로 HealthBench 1100 배치 결과 비교성 단절 | 중간 | 4-A 에서 평가함수는 동일(호스트 GPT 평가) 유지 — 생성 경로만 HTTP 화. 전환 전후 동일 시나리오 10건 비교 리포트 |
| OIDC 전환 실수로 호스트→RAG 502 전면 장애 | 중간 | 4-C 를 분리 전에 단독 수행(변수 격리). RAG_TRUST_SECRET 경로 병행 유지. 1커맨드 롤백 문서화 |
| submodule 갱신 누락으로 호스트/RAG 의 compliance-rules 버전 분기(가드레일 ≠ 평가 기준) | 중간 | CI 에 submodule SHA 일치 검사. guidelines.json 버전 API(get_guideline_version)로 런타임 버전 노출·모니터링 |
| SSE 포맷 변경 시 프론트 전면 파손(암묵 계약) | 중간 | 프록시 규약·SSE 이벤트 스키마를 신규 repo README 에 공개 계약으로 문서화. 변경은 additive-only 정책 |
| dbcommon PG 풀이 서비스별 독립 생성 → 커넥션 총량 증가 | 낮음 | Cloud SQL max_connections 대비 풀 상한 합산 점검(현재 1-10×서비스). 필요 시 풀 파라미터 env 화 |
| gcloud builds submit + submodule 미초기화 업로드 | 낮음 | 배포 스크립트에 `git submodule update --init` 선행 + 존재 검증 |

## 4. 분리 후 데이터/소유권 (최종 상태)

- **물리 DB 공유 유지**(Cloud SQL medical-db / medical_app·medical_app_dev) — 논리 소유권 분리:
  - RAG repo 소유: kb_sources/kb_documents/kb_chunks/rag_queries/kb_feedback/llm_providers/embedding_providers/review_queue_items/rag_conversation_state + email_notifications/embedding_migration_log. 마이그레이션은 신규 repo 의 migrate_runner 가 단독 관리.
  - 호스트 소유: users/conversations/messages/scenarios/settings/test_runs/sessions 등 — db.py init_db 자체 관리.
  - 교차 접근(수용된 부채): conversations INSERT 1곳(감사), scenarios READ 1곳(배치, D3 후 호스트 내부화로 소멸).
- 향후(선택): DB 사용자 분리(rag 계정에 RAG 테이블만 GRANT)로 소유권을 권한 수준에서 강제.
