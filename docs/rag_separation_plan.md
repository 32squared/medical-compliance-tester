# RAG 저장소 분리 — 로드맵 & 진행 현황

> RAG 서브시스템을 테스트 시스템에서 분리해 **독립 저장소 + 단일 HTTP 엔드포인트**로
> 만드는 다단계 리팩터의 살아있는 계획서. 테스트 시스템은 SKIX 와 동일한 방식으로
> RAG 를 호출한다(리버스 프록시 규약 통일).

브랜치: `refactor/rag-modular`

---

## 단계 현황

| Phase | 내용 | 상태 |
|---|---|---|
| **0** | 선행 디커플링 (conversations ALTER 호스트 이전, 마이그레이션 러너, 배포 연결) | ✅ 완료 |
| **1** | conversations 런타임 결합 해제 — emergency_state → RAG 소유 `rag_conversation_state` | ✅ 완료 (PG 실증 대기) |
| **2-A** | 연결 레이어 `dbcommon` 추출 (facade 재export) | ✅ 완료 (PG 실증 대기) |
| **2-B** | consultation_checklists.json 단일 로더 | ✅ 완료 |
| **2-C** | compliance-rules 경계 문서화 | ✅ 본 문서 |
| **3** | RAG 독립 HTTP 서비스 + 호스트 리버스 프록시 (additive, 플래그) | ✅ 완료 + **dev PG 실증 + 브라우저 e2e 확인** |

> **dev 실증 완료(2026-06-06):** 독립 RAG 서비스(medical-rag-dev) 배포 →
> verify_rag_separation 하니스 **ALL PASS**(health/인증/chat SSE STOP+citations, 한글이름 포함).
> 즉 Phase 1(rag_conversation_state)·Phase 2-A(dbcommon 풀)이 **실제 Postgres 에서 동작**.
> 호스트(medical-compliance-tester-dev)는 RAG_SERVICE_URL 주입돼 **분리 모드 활성**.
> **브라우저 인증 경로 최종 확인(2026-06-06, rev 00098):** 로그인 상태에서 RAG 채팅 1회 →
> 답변 본문 + 인용 + 평가(컴플라이언스/문진) 전부 정상 표시. 초기 "답변 안 달림"은
> 호스트→브라우저 SSE relay 가 `resp.read(1024)`(버퍼 채워질 때까지 블록)였던 것이 원인 →
> `resp.read1(65536)` 로 수정해 즉시 패스스루(commit 3995ea3)되며 해소.
> 롤백: `.\deploy-dev.ps1`(RagServiceUrl 없이) → in-process 복귀.
>
> **지연 관찰(보류 — 지금 고치지 않음):** 동일 테스트 타이밍 분해 →
> RAG 총 39.9s 중 **LLM 생성 33.25s**(1785자 스트리밍)가 지배적 + RAG 서비스 **콜드 스타트**
> (min-instances=0). 그 위에 호스트 프록시 relay + GPT 컴플라이언스/문진 평가가 직렬 누적.
> 향후 개선 후보(미착수): ① RAG `min-instances=1` 로 콜드스타트 제거,
> ② `[RAG-PROXY]` 진단 print 에 `flush=True`(현재 stdout 버퍼링으로 로그 누락),
> ③ 평가(컴플라이언스/문진)를 답변 스트리밍과 병렬화. **사용자 지시로 지연 수정은 보류.**
| **4** | 저장소 분리 + 독립 배포 (dbcommon/compliance-rules 공유 패키지화) | 📋 **계획 수립 완료** → [rag_phase4_split_plan.md](rag_phase4_split_plan.md) (2026-06-10 전수조사 기반, 착수 전 결정 D1~D7 대기) |

### Phase 3 구성 (additive — RAG_SERVICE_URL 미설정 시 현재 동작 불변)
- `rag_server.py`: RagRoutesMixin 재사용 독립 BaseHTTPServer. 8개 헬퍼 자체 구현,
  인증은 신뢰헤더(X-User-*) + 선택 RAG_TRUST_SECRET. 믹스인 무변경.
- `proxy_server.py`: RAG_SERVICE_URL 설정 시 /api/rag/* 4개 디스패치를 `_proxy_to_rag`
  로 리버스 프록시(SSE 스트리밍 패스스루, 쿠키→신뢰헤더 변환 = same-origin 유지).
- `entrypoint.sh`: RUN_MODE=rag → rag_server.py.
- `deploy-rag.ps1`: 독립 RAG Cloud Run 서비스 배포.
- 프론트(chat_tester.html): **변경 불필요** — 리버스 프록시라 same-origin 유지.

### 분리 모드 활성화 (검증은 나중에)
1. `$env:DB_PASSWORD='...'; .\deploy-rag.ps1`  → 독립 RAG 서비스 배포(URL 획득).
2. `.\deploy-dev.ps1 -RagServiceUrl <rag-url> [-RagTrustSecret <secret>]`
   → 호스트가 /api/rag/* 를 그 서비스로 프록시(분리 모드).
3. `python tests/verify_rag_separation.py --rag-url <url> ...` → 분리 경로 스모크 검증.
4. 롤백: deploy-dev.ps1 을 -RagServiceUrl 없이 재배포 → in-process 복귀.

---

## 경계 정의 (무엇을 어디로)

### dbcommon (연결 공유 레이어) — Phase 2-A 완료
`dbcommon.py` = `get_conn / _p / _ph / _upsert / _row_to_dict / _pg_json_loads(_or) / _now`
+ `DATABASE_URL / DB_PATH / _use_postgres / _pg_pool / _ensure_pool`.
- `_use_postgres` 는 **import 시점** DATABASE_URL 유무로 확정 → facade 재export 안전.
- PG 풀은 첫 `get_conn` 에서 **lazy 생성**.
- `db.py` 는 dbcommon 을 facade 재export → 기존 `from db import get_conn` 무변경.
- **런타임 DB 재설정은 dbcommon 을 패치**할 것(get_conn 이 dbcommon 전역을 읽음).
- Phase 4: 공유 pip 패키지로 물리 분리.

### compliance-rules (가드레일/고지/체크리스트) — 경계만 정의, 물리 분리는 Phase 4
구성: `analyzer.py + config.py + guideline_loader.py + guidelines.json +
violation_rules.json + consultation_checklists.json`.
- 의존: `analyzer → config → guideline_loader → guidelines.json/violation_rules.json`.
- RAG 핫패스(가드레일 `rag_engine` ComplianceAnalyzer, 고지 get_fixed_notices)가
  in-process 로 사용 → HTTP 아닌 **공유 라이브러리**가 적합.
- in-repo 에선 이미 같은 레포라 import 가능. 진짜 분리는 Phase 4 패키징.

### 데이터 소유권
- **RAG**: kb_sources/kb_documents/kb_chunks/rag_queries/kb_feedback/llm_providers/
  embedding_providers/review_queue_items + `rag_conversation_state`(Phase 1 신설).
- **호스트**: users/conversations/messages/scenarios/settings/comments/test_runs/
  sessions/response_feedback/preference_pairs/arena_*. 평가 API(/api/evaluate*).
- **공유**: dbcommon(연결), compliance-rules(룰).

---

## 운영 메커니즘 (Phase 0 산출물)

### 마이그레이션 러너 `migrations/migrate_runner.py`
- `schema_migrations` 추적 + `--status / --baseline / --apply / --sync`.
- 배포 연결: `deploy-dev.ps1 [1.5/3]` → `db-migrate-dev` Job(RUN_MODE=migrate, `--sync`).
- 도입: 최초 `--sync` 가 현재 스키마를 baseline 채택, 이후 010+ 만 apply.
- **dev 는 009 baseline 채택 완료**(2026-06-06 dev 배포에서 PG 실증).

---

## 남은 작업 / 선결 조건

1. **PG 실증 (대기)** — Phase 1 `rag_conversation_state`, Phase 2-A dbcommon 풀 lazy 생성은
   SQLite 로만 검증. 다음 **dev 배포 1회**로 PG 확정.
2. **prod baseline** — RAG DDL 을 db.py 에서 떼는 작업(Phase 4 토대)은 운영 DB 채택이 선행.
   `deploy-migrate.ps1 -Prod -Execute -Wait` 또는 운영 배포(권한 필요).
3. **Phase 2-B 보류 사유** — consultation_checklists.json 의 4개 로더가 반환 형태가
   상이(raw list vs `{"symptoms":{...}}` vs db 시드용). 단일 로더화는 호출처별 어댑터가
   필요해 in-repo 가치 대비 위험이 있어, **Phase 4 패키징과 함께** 처리 권장.
4. **Phase 3 하드블로커 — 해소됨** — 리버스 프록시 채택으로 same-origin 유지(쿠키/CORS
   블로커 회피), 8개 메서드는 rag_server 에서 자체 구현, SSE 는 프록시 스트리밍 패스스루.
   남은 건 분리 모드 end-to-end 라이브 검증(deploy-rag + RAG_SERVICE_URL 후).
5. **Phase 4 (저장소 분리)** — git filter-repo 로 RAG 모듈군 + 마이그레이션 + Dockerfile 을
   새 repo 로 이동, dbcommon/compliance-rules 공유 패키지화, 서비스 간 IAM 인증.
   GitHub 저장소 생성·CI/CD 등 인프라 결정이 필요해 자동 수행하지 않음.

---

## 변경 이력 (이 브랜치)
- `fix(rag)` 인용·평가 복구(문진 NameError 등)
- `refactor(rag)` conversations ALTER 호스트 이전 (Phase 0)
- `feat(db)` 마이그레이션 러너 + schema_migrations (Phase 0)
- `feat(deploy)` 러너 배포 연결 (Phase 0)
- `feat(rag)` emergency 상태머신 RAG 이관 (Phase 1)
- `refactor(db)` 연결 레이어 dbcommon 추출 (Phase 2-A)
- `docs(rag)` 분리 로드맵 문서 (Phase 2-C)
- `feat(rag)` RAG 독립 서비스 + 리버스 프록시 (Phase 3, additive)
