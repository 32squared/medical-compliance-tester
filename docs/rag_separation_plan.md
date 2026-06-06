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
| **2-B** | consultation_checklists.json 단일 로더 | ⏸ 보류 (아래 사유) |
| **2-C** | compliance-rules 경계 문서화 | ✅ 본 문서 |
| **3** | RAG 를 독립 HTTP 서비스로 승격 (RagRoutesMixin 제거, 호스트 리버스 프록시) | ⬜ |
| **4** | 저장소 분리 + 독립 배포 (dbcommon/compliance-rules 공유 패키지화) | ⬜ |

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
4. **Phase 3 하드블로커** — 인증(동일-origin 쿠키 → 리버스 프록시 + 신뢰헤더 변환),
   RagRoutesMixin 의 ProxyHandler 8개 메서드 + SSE 소켓 이식, CORS.

---

## 변경 이력 (이 브랜치)
- `fix(rag)` 인용·평가 복구(문진 NameError 등)
- `refactor(rag)` conversations ALTER 호스트 이전 (Phase 0)
- `feat(db)` 마이그레이션 러너 + schema_migrations (Phase 0)
- `feat(deploy)` 러너 배포 연결 (Phase 0)
- `feat(rag)` emergency 상태머신 RAG 이관 (Phase 1)
- `refactor(db)` 연결 레이어 dbcommon 추출 (Phase 2-A)
