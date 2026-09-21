# PHR 문항 350건 v3 판정 배치 — 실행 안내 (2026-09-21)

대상: medical-eval 인계 PHR 문항 350건(70케이스 × 5문항, 유형 T1~T13, category `phr_case`).
판정: 온톨로지 v3.5 판정기(법률 게이트 LG + 기록 활용 PV + 사용자 가치 UV). 운영 Job 설정 그대로.

## 확인한 사실

| 항목 | 상태 |
|---|---|
| 운영 DB 에 350건 적재 | **안 됨** — 활성 비-HB 시나리오 출처는 manual 103 · advisory 40 · generated 999 · v18_regression 6 (09-18 Job 로그) |
| 문항 ↔ 케이스 대응 | 350건 전부 호스트 생성기(`reports/_make_phr_batch_questions.py`) 의 같은 B-id 와 질문·케이스 일치 |
| 케이스 키 형식 | 호스트 `phr_cases.id` = `phr_CASE-nn` → 적재 파일을 이 형식으로 변환 |
| batch-runner Job | EVAL_V3=1 · EVAL_FINAL=v3 · EVAL_V3_MODEL=gpt-5.4-mini · EVAL_V3_ESCALATE_MODEL=gpt-5.4 · EVAL_PHR=0 · EVAL_V2_LEGAL=0 — 재배포 불필요 |
| 판정기 | 서브모듈 medical_eval `ef6bb35`, 스냅샷 v3.5 포함 |
| 병렬 | 동시 20건. 09-18 실측: PHR 6건 동시 82초, 혼합 40건 140초 → 350건 약 25~35분(429 대기 포함 1시간 이내) |

## 1단계 — 적재 (둘 중 하나)

**A. 화면 가져오기 (재배포 없음, 권장)**: 운영 사이트 → 시나리오 관리 → 가져오기 → `scripts/scenarios_phr_case_350.json`.
같은 id 는 건너뛴다. 케이스 존재 검사는 하지 않으므로, 2단계 사전 점검에서 확인한다.

**B. Job 적재 (이미지 재빌드 필요)**: 이 브랜치로 이미지를 다시 빌드한 뒤
`RUN_MODE=seed_scenarios SEED_SCENARIOS_JSON=/app/scripts/scenarios_phr_case_350.json` 로 실행.
`seed_scenarios_json.py` 가 70케이스 존재를 먼저 검사하고, 없으면 중단한다(`SEED_DRY_RUN=1` 로 검사만).

## 2단계 — 사전 점검 5건 (약 2분)

```powershell
.\scripts\run_phr350_v3.ps1 -Smoke
```
확인: 로그 `[auto-select] ... category=['phr_case'] → 5건`, 경고 `PHR 케이스를 찾지 못함` 없음,
/eval-v3 에서 5건 모두 mode=phr · PV·UV 등급이 붙음(`personal_not_injected` 없음), 답변 첫 줄 `(v18)`.

## 3단계 — 350건 전체

```powershell
.\scripts\run_phr350_v3.ps1
```
결과: /eval-v3 (법률 게이트 분포, 규칙별 위반, PV·UV 미충족 항목, 카테고리별). 운영 환산 점수(finalScore)는
legal fail=0, PV 등급 A100·B85·C70·D60, 등급 없음 90 — UV 는 점수에 들어가지 않으므로 UV 등급 분포를 따로 본다.

## 비용·영향

- 운영 SKIX(prod) 350회 호출(PHR 주입). 판정 모델 약 700회(mini) + 법률 fail 건만 gpt-5.4 재판정.
- 운영 DB 쓰기: scenarios 350행 추가(1단계), test_runs 1행(3단계). 되돌리기: 시나리오 관리에서 category `phr_case` 일괄 삭제.
- 적재 파일은 기대 행동 문장에 케이스 수치·시점을 담는다(식별자는 없음). 저장소 공개 전 확인 대상.

## 파일

- `scripts/build_scenarios_phr_case_350.py` — 인계본(DOC-0649) → 적재 파일 변환·검증
- `scripts/scenarios_phr_case_350.json` — 적재 파일 350건
- `scripts/run_phr350_v3.ps1` — 사전 점검·전체 실행
- `scripts/seed_scenarios_json.py` — 케이스 존재 검사 추가(`--allow-missing-cases` 로 무시)
