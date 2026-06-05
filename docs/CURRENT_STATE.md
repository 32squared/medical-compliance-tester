# 현재 운영 상태 (2026-05-15 기준)

## PROD 환경
- 공식 URL: https://medical-compliance-tester-cbtevhmzrq-du.a.run.app
- 최신 revision: **medical-compliance-tester-00138-fjz**
- 메모리/CPU: 8Gi / 2 vCPU
- 인스턴스: min=3, max=20, concurrency=1
- 모델: gpt-5.4 (OpenAI)

## 시나리오 데이터
- 총 1100건 (manual 100 + generated 1000)
- 카테고리: 17개 (수동 한글 10 + 자동생성 영문 6: emergency/diagnosis/general/prescription/treatment/edge)

## 최근 배치 실행 결과

### 1차 LLM-only 단일 1100건 (3.5시간)
- runId `batch-20260514-175526-0ae23b` — 727건 처리 후 cancelled (Cloud Run 인스턴스 lifecycle)
- 누락분 재시도 5회 거쳐 1099/1100 완료
- 24분 만에 LLM 재평가 완료

### 2차 LLM-only 4 shard 병렬 (61분)
- 4 shard: bb8345 / bc5ca6 / 98cd31 / fd9494
- 950/951 처리 (shard 2에서 1건 누락)
- 6배 빠른 처리

### 통합 runId (merge endpoint)
- **`merged-20260515-111537-6e6f0f`**
- 6개 source runId 합산 → 단일 entity
- 1100건 / pass 632 (57.5%) / fail 467 / error 1

## 코드 변경 이력 (master branch)

| Commit | 내용 |
|---|---|
| `bd0593d` | POST /api/history/merge endpoint |
| `bf64dd8` | history.html null check 강화 |
| `208bc68` | 4 shard 병렬 + concurrency=1 + max-instances=20 + MAX_BATCHES=4 |
| `fe9b8bd` | 메모리 2Gi → 8Gi |
| `5554def` | API 에러 카테고리 + 부분 응답 + 재시도 추적 |
| `e524966` | TTFT/응답 종료/생성 시간 metric |
| `76523f3` | GPT 평가 → 컴플라이언스 평가 라벨 통일 |
| `321c6dd` | LLM-only (정규식 평가 제거) |
| `900b171` | P0+P1 검토 사이클 도구 (cross-tab/필터/A-B비교) |

## 진행 중 작업
- ✅ 1100건 평가 완료 + 통합 runId 생성
- ⏳ **Cloud Run Jobs 이전 (계획서: docs/CLOUDRUN_JOBS_MIGRATION.md)**
  - Phase 1~5 작업 일정 1일
  - 다음 세션에서 시작 예정

## OpenAI 계정 상태
- 모델: gpt-5.4
- quota 정상 (충전 완료, 사용자 액션 후)
- 1100건 LLM 평가 비용: 약 $1.50~3.00 (gpt-5.4 기준)

## 운영 advisor 현황
- rexsoft01~07 (7개 자문위원 계정)
- 권한: tester role + advisor 가시성 차단(Arena 차단 등)
- 커멘트 수정 기능 적용됨 (자신 + admin만 수정 가능)

## 기능 활성 상태
- ✅ Magic Link 임시 로그인 (admin → 사용자)
- ✅ 권한 관리 (advisor / tester / admin + 11 세부 권한)
- ✅ Chat Arena (A/B 비교)
- ✅ 컴플라이언스 평가 (LLM gpt-5.4)
- ✅ 문진 평가 (5축 100점)
- ✅ 응답 시간 metric (TTFT/생성/총 시간)
- ✅ API 에러 추적 (분류/HTTP 코드/재시도/부분 응답)
- ✅ 배치 리포트 (카테고리×등급/위반 역참조/메타 통계/A/B 비교)
- ✅ 세그먼트 필터
- ✅ 시나리오 ↔ 시나리오 history merge

## 다음 우선순위 (Cloud Run Jobs 이후)
1. (선택) 1100건 컴플라이언스 평가 결과 분석 → 가이드라인 보강
2. (선택) Phase 2 Arena 보강 (κ 일치도, 모델 선호도 대시보드)
3. (선택) 시계열 패스율 차트 / 가이드라인 룰별 효과 추적
