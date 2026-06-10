# Phase 4 팀 운영 프로토콜 — 오케스트레이터 + 품질 게이트 구조

> [rag_phase4_split_plan.md](rag_phase4_split_plan.md) 실행을 위한 에이전트 팀 구조.
> 핵심 원칙: **모든 작업 패키지는 정합성 게이트를 통과해야만 커밋된다.**

## 팀 구성 (team: `rag-split`)

| 역할 | 이름 | 타입 | 책무 |
|---|---|---|---|
| 통합/최종결정 | (메인 세션) | — | 사용자 소통, 작업 패키지 발주, 최종 커밋/배포, 태스크 목록 관리 |
| **오케스트레이터** | `orchestrator` | team-lead | 계획서→작업 패키지 분해, 순서/병렬성 판단, 패키지별 완료 기준(DoD) 정의, 진행 추적 |
| **품질 게이트** | `qa-gate` | qa-reviewer | 패키지 완료 시마다 `python scripts/check_consistency.py` 실행 + 코드 리뷰(보안/호환성/로직). **거부권 보유** |
| 구현 워커 | (패키지별 스폰) | backend-dev / devops / frontend-dev | 단일 작업 패키지 구현. 완료 시 변경 요약 보고 |

## 작업 루프 (패키지 단위)

```
1. 발주    메인 → orchestrator: 다음 패키지 범위 확인 (계획서 단계 기준)
2. 분해    orchestrator: 패키지 정의(대상 파일·DoD·검증 명령·리스크) 반환
3. 구현    메인 → 워커 스폰(병렬 가능): 구현 + 자체 문법검증
4. 게이트  메인 → qa-gate: check_consistency.py + 리뷰 → PASS/FAIL 판정
5. 판정    FAIL → 워커 재작업(같은 에이전트 SendMessage 재개) → 4 반복
           PASS → 메인이 커밋 (커밋 메시지에 게이트 결과 명기)
6. 추적    메인: 태스크 완료 처리, orchestrator 에 다음 패키지 진행 통보
```

## 정합성 게이트 (`scripts/check_consistency.py`)

| 검사 | 내용 | Phase 4 에서의 의미 |
|---|---|---|
| py-compile | 루트 *.py 54개 + migrate_runner 컴파일 | 회귀 차단 |
| js-syntax | 루트 HTML 16개 `<script>` 문법 | 프론트 회귀 차단 |
| json-data | guidelines/violation_rules/checklists 파싱 | 룰 데이터 무결성 |
| shared-symbols | dbcommon·analyzer·config·guideline_loader·consultation_loader 공개 심볼 15개 | **4-B 패키지 공개 API 의 원본 계약** |
| mixin-contract | rag_routes 가 쓰는 헬퍼 8개가 proxy_server/rag_server 양쪽에 존재 | in-process↔독립 서비스 동작 동등성 |
| import-boundary | RAG↔HOST 교차 import 금지 + **허용목록 2건** | 허용목록이 비면 분리 완료. 절단 후 목록서 제거 = DoD |
| migrations | SQL 파일 규약 | 마이그레이션 이식 안전성 |

**운영 규칙:**
- `ALLOWED_COUPLINGS` 는 **추가 금지, 제거만 허용**. 새 결합이 필요하면 설계 회귀이므로 메인이 사용자에게 보고.
- 4-A 완료 = `('batch_eval_rag','proxy_server')` 제거 후 그린. 4-E 완료 = `('proxy_server','rag_routes')` 제거 후 그린.
- 파일 분류(RAG/SHARED/HOST)는 검사기 상단 상수 = 분리 매니페스트. 신규 파일 생성 시 분류 추가 필수(미분류 = HOST 취급).
- repo 분리(4-E) 후에는 이 검사기가 양쪽 repo CI 로 이식된다(경계 검사는 "상대편 모듈 import 자체 금지"로 단순화).

## 게이트 판정 기준 (qa-gate)

1. `check_consistency.py` exit 0 (필수)
2. 기존 qa-reviewer 체크리스트: XSS/SQL 플레이스홀더/인증 가드/`_p()`·`_ph()` 듀얼 DB/DOM null 체크
3. 패키지 DoD 충족 (orchestrator 가 정의한 것)
4. 판정 리포트: PASS / FAIL+사유표(Issue·Severity·File·Line)

## 에스컬레이션

- 워커 2회 재작업에도 FAIL → orchestrator 가 패키지 재설계
- 계획서와 충돌 발견 → 메인이 계획서 갱신 후 사용자 보고
- prod 관련 작업(4-D)·시크릿·외부 publish 는 **반드시 사용자 승인 경유** (에이전트 단독 실행 금지)
