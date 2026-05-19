# HealthBench 운영 가이드

OpenAI HealthBench 영문 데이터셋을 활용한 SKIX 의료 응답 평가의 운영 흐름 정리.

## 1. 시스템 개요

| 구성 요소 | 위치 / URL |
|---|---|
| 운영 페이지 | `/healthbench` |
| 시나리오 상세 (모달) | `/healthbench/scenario?id=HB-XXXX&run=run-...` |
| 학습 자료 | `/healthbench/about` |
| 리포트 (batch별) | `/api/history/<runId>/healthbench-report` |
| 배치 실행 endpoint | `POST /api/healthbench/run-batch-job` |
| import 스크립트 | `scripts/import_healthbench.py` |
| Cloud Run Job | `batch-runner` (실행) / `import-healthbench` (데이터 로드) |

## 2. 데이터셋 구조

| 데이터셋 | 건수 | 의미 |
|---|---|---|
| Standard (oss_eval) | 5,000 | 전체 데이터 |
| Hard | 1,000 | Standard 의 어려운 시나리오 부분집합 |
| Consensus | 3,671 | 의사 합의 명확 부분집합 |
| Hard ∩ Consensus | 586 | 둘 다 |

**현재 PROD DB**: Hard subset 1,000건 전체 import 완료.

## 3. 권한

| 역할 | HB 페이지 | HB API | Batch 실행 |
|---|---|---|---|
| Admin | ✓ | ✓ | ✓ |
| Tester (기본 권한 = view_history 포함) | ✓ | ✓ | ✓ |
| Advisor (view_history 미부여) | ✗ | ✗ | ✗ |

권한 변경: `/settings` → 사용자 관리 (Admin 만 가능)

## 4. 운영 워크플로

### 4.1 시나리오 검토 (사전 분석)
1. `/healthbench` 접속 → admin 로그인
2. Subset 토글 선택 (전체 / Hard / Consensus / Hard ∩ Consensus)
3. Theme 카드 클릭 → 그 theme 의 시나리오 목록 펼침
4. 시나리오 row 클릭 → 모달에서 turns, rubric 정의 확인

### 4.2 Batch 실행
1. Subset 선택
2. "▶ Job 으로 실행" 버튼 클릭 → 확인 prompt → 실행
3. 진행 표시줄로 % 추적 (5초마다 자동 갱신)
4. Cloud Run Job (`batch-runner`) 으로 위임됨 — service thread 와 분리

### 4.3 결과 분석
1. 최근 HB 배치 이력에서 run 클릭 → 자동 리포트 표시
2. **요약** — 평균 점수 / 통과율 / 루브릭 met / 가중 점수
3. **Theme별 점수** — global_health 등 어느 영역이 약한지
4. **Axis별 점수** — safety/completeness/accuracy 등 어느 축이 약한지
5. **시나리오별 (점수 낮은 순)** — 클릭 시 상세 모달 (turns + rubric items)

### 4.4 개별 시나리오 분석
- 모달의 Rubric 평가 상세에서 각 item 의 met/not-met + GPT 설명 확인
- 4종 배지:
  - ✅ MET (양수 충족) — 좋음
  - ❌ MET (negative) — 부정 항목 발생 (벌점)
  - ⚪ MISSED — 양수 항목 놓침
  - ✓ AVOIDED — 부정 항목 회피 (좋음)

## 5. 점수 해석

| 점수 구간 | 의미 | 색상 |
|---|---|---|
| 75-100 | 우수 | 초록 |
| 50-74 | 통과 (PASS 기준) | 파랑 |
| 25-49 | 미흡 | 노랑 |
| 0-24 | 심각 | 빨강 |

PASS 판정 기준: **rubric score ≥ 50**

## 6. 자주 쓰는 명령

### 시나리오 import (data 변경 시)
```bash
# Hard 1,000건 전체 (현재 적용)
gcloud run jobs execute import-healthbench --region asia-northeast3 --wait

# 다른 import — 스크립트 args 변경 + image rebuild
python scripts/import_healthbench.py --source consensus --all --reset  # Consensus 3671건
python scripts/import_healthbench.py --reset                            # Standard 5000 stratified 100건
```

### Batch 실행 (CLI)
```bash
# 운영 페이지의 버튼 권장. 굳이 CLI 면:
gcloud run jobs execute batch-runner --region asia-northeast3 \
  --update-env-vars "^|^RUN_ID=cli-$(date +%s)|SCENARIO_IDS_JSON=[\"HB-XXX\"]|RUN_BY=cli"
```

### 분석 / 점검
```bash
# 점수 분포 분석 (Cloud Run Job 형태로 실행)
ANALYZE_RUN_ID=hb-full-... python scripts/analyze_run_scores.py --histogram

# 특정 시나리오 진단
VERIFY_SCENARIO_ID=HB-XXXX python scripts/diagnose_hb_scenario.py

# API 응답 진단
VERIFY_SCENARIO_ID=HB-XXXX python scripts/diagnose_api_response.py
```

### 옛 batch cleanup
```bash
# 식별만 (dry-run)
python scripts/cleanup_old_batches.py --pattern 'live-verify-'

# 실제 삭제
python scripts/cleanup_old_batches.py --pattern 'live-verify-' --delete
```

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| 시나리오 상세 모달이 비어있음 | 브라우저 JS 캐시 또는 fetch 실패 | Ctrl+Shift+R 강제 새로고침, F12 Console 에러 확인 |
| 시나리오 클릭 시 404 | 시나리오 reset 후 옛 run 의 ID 가 현재 DB 에 없음 | 자동 fallback 동작 — "다른 run 의 결과 표시" 배너 확인 |
| batch 가 중간에 멈춤 | SKIX 응답 timeout (read_timeout=900s) | 시나리오별 자동 retry (최대 2회). retry 후도 실패면 error 처리 |
| HB 카테고리가 안 보임 | settings.categories 에 healthbench 누락 | `scripts/add_healthbench_category.py` 실행 |
| 인증 403 ("자문위원은...") | view_history 권한 없음 | admin 페이지에서 권한 부여 |

## 8. 데이터 확장 로드맵

| Phase | 시점 | 규모 | 비용 (OpenAI) | 소요 시간 |
|---|---|---|---|---|
| Phase 1 (완료) | 이번 주 | 100건 stratified | ~$0.50 | 30분 |
| Phase 2 (현재) | 이번 주 | **Hard 1,000건** | ~$5 | 2-3시간 |
| Phase 3 | 1-2주 후 | Consensus 3,671건 | ~$18 | 6-8시간 |
| Phase 4 | 3-4주 후 | Standard 5,000건 (4 batch 분할) | ~$25 | 16-20시간 누적 |

Phase 4 는 단일 batch 가 아닌 1,250건 × 4 분할 + `/api/history/merge` 로 통합 리포트.

## 9. 운영 자산

| 자산 | 보존 정책 |
|---|---|
| Cloud Run Service `medical-compliance-tester` | 운영 |
| Cloud Run Job `batch-runner` | 운영 |
| Cloud Run Job `import-healthbench` | 보존 (재 import 가능) |
| 일회용 Jobs (`verify-run`, `add-healthbench-category` 등) | 사용 후 삭제 |
| PROD DB `scenarios` HB-* (1,000건) | 운영 |
| `test_runs` 의 HB batch 결과 | 보존 (분석 대상) |

## 10. 참고

- OpenAI HealthBench: <https://github.com/openai/simple-evals>
- 내부 학습 페이지: `/healthbench/about`
- 본 시스템 디자인: `scripts/import_healthbench.py`, `proxy_server._skix_replay`, `proxy_server._evaluate_rubric`
