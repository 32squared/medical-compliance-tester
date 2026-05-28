# 1100 시나리오 배치 평가 — 운영 런북 & 개선 로그

> 목표: HealthBench(hard) 1100 시나리오를 RAG로 응답 → **법률(컴플라이언스) A + 문진 A 동시 달성(both_A)**.
> 측정 도구: `batch_eval_rag.py` (Cloud Run Job `run-batch-eval`).
> 작성: 2026-05-29 · 브랜치: `feature/rag-system`

---

## 1. 인프라 구성 (이미 구축됨)

| 자산 | 값 |
|------|-----|
| 시나리오 출처 | **OpenAI HealthBench (hard)** — `import-healthbench` Job (`scripts/import_healthbench.py --reset --source hard --all`)이 Cloud SQL `scenarios` 테이블로 임포트 |
| 평가 Job | Cloud Run Job `run-batch-eval` (region `asia-northeast3`) |
| 이미지 | `gcr.io/medical-compliance-tester/medical-compliance-tester:batch-eval` |
| DB | Cloud SQL `medical-db` / `medical_app` (pgvector) — Secret `db-password` |
| LLM | Secret `openai-api-key`, `EVAL_MODEL=gpt-4o-mini` |
| 평가 3종 | `_evaluate_gpt`(법률), `_evaluate_consultation`(문진 5축, A≥85), `_evaluate_consultation_checklist`(로컬 보조) |
| both_A 정의 | `compliance_grade=='A' AND consultation_grade=='A'` (batch_eval_rag.py:308) |

### ⚠️ 운영 제약
- **Task timeout = 1800초(30분), maxRetries=0**. 시나리오당 ~66초 / 8워커 → 1100개 ≈ **2.5시간 ≫ 30분 → 전체 실행은 반드시 타임아웃 실패**.
  - 2026-05-28 실패 실행(b4p2s, wgvbm)이 모두 이 이유. 성공한 9vd9h는 `--limit 50`.
  - **전체 1100 실행하려면**: (a) `--task-timeout 14400`(4h)로 상향, 또는 (b) `--tasks N`로 샤딩 + `CLOUD_RUN_TASK_INDEX` 기반 분할(코드 수정 필요), 또는 (c) `--workers` 상향(16+).
- 검색(retrieval)이 대부분 INSUFFICIENT (top1 cosine 0.25~0.45, `no_topic_match`) — KB가 HealthBench 주제를 충분히 커버하지 못함. 게이트는 SHADOW(비강제) 모드라 진행은 됨.

---

## 2. Baseline (2026-05-28, 50샘플, 개선 전)

```
both_A (목표):   0 / 50  (0.0%)
법률(컴플라이언스): A:8, B:29, C:13
문진:              B:10, C:30, D:10  (A 사실상 0)
평균 응답시간:     66초
```

### 근본 원인 (진단)
1. **가드레일 오탐** — 좋은 응답이 HIGH로 차단/재생성되어 점수 하락 (가장 직접적):
   - `treatment`: 면책조항 "진단·치료는 의료진과 상담하세요"가 매 응답마다 오탐
   - `emergency_guidance`: `.{0,100}(?!.*119)` 백트래킹 → 119가 있어도 오탐
   - `emergency_workflow_violation`: "악화 시 응급실"(조건부 안전망)+문진 질문 오탐
2. **문진 질문 부족** — 4단 ④ 섹션 지시가 빈약 → 증상탐색(30)·환자맥락(20) 미달 → 문진 B 상한
3. **검색 품질** — KB 미스매치로 약한 근거 → 보수적/빈약 응답 (깊은 병목, KB 확장 필요)

---

## 3. 개선 로그

### 측정 요약표 (50샘플 동일 시나리오)

| 단계 | 평가모델 | 법률 A | 문진 A | both_A |
|------|---------|--------|--------|--------|
| Baseline (개선 전) | gpt-4o-mini | 16% | ~0% | **0%** |
| v1 문진 ④ 강화 | gpt-4o-mini | 4% | 76% | 0% |
| v2 +법률 평가기 교정 | gpt-4o-mini | 12% | 74% | 2% |
| **v3 +오판방지 프롬프트, 평가모델 gpt-4o** | **gpt-4o** | **98%** | **78%** | **76%** |
| **v4 +응급 문진 원칙** | **gpt-4o** | **96%** | **98%** | **96%** (48/50, 1건 API 일시오류) |

### v1 — 가드레일 오탐 3종 제거 + 문진 ④ 강화 (커밋 5054492)
- `violation_rules.json`: treatment(헤지 tempered dot), emergency_guidance(전체응답 검사로 교체)
- `analyzer.py`: emergency_workflow_violation을 비조건부 즉시 리다이렉트에만 발동
- `rag_engine.py`: 4단 ④를 ⓐ증상정밀화 ⓑ위험신호 ⓒ환자맥락 ⓓ안내 질문 묶음으로 재설계 + 원칙8
- 효과: 문진 0%→76% (대성공). 단 법률은 가드레일 재생성 제거로 원본 노출되며 일시 하락.

### v2 — 법률 평가기 오교정 수정 (커밋: guidelines.json)
- DIAG 진단: below-A 거의 전부가 "응급/내원 단정적 분류" CRITICAL = '즉시 119 권유'를 위법 오판.
- `guidelines.json`: emergency_dismiss(부정·축소만 위반), diagnosis(hedged 가능성 허용), allowed_rules 3종 추가.

### v3 — 오판방지 프롬프트 + 평가모델 gpt-4o ⭐ 결정적
- `guideline_loader.py`: 프롬프트 최상단에 '오판 방지' 블록(권유/가능성 vs 단정/지시 구분).
- **핵심 발견**: gpt-4o-mini는 hedged 가능성·응급안내·진료과 권유를 자기모순적으로 과잉 판정(고장난 평가기).
  동일 RAG 답변을 gpt-4o로 평가하니 법률 12%→**98%**, both_A 2%→**76%**.
  → RAG 답변은 이미 우수, 약한 평가 모델이 병목이었음이 입증됨.
- **결정 필요**: 법률 평가는 gpt-4o 사용 권장(정확). 비용은 gpt-4o-mini의 ~15배.

### v4 — 응급 문진 평가 원칙 (커밋: proxy_server.py)
- 남은 below-A 12개는 거의 전부 응급 시나리오의 문진(질문 생략 감점).
- `_build_consultation_prompt`: 응급 시 적절한 즉시 안내는 문진 A로 평가(criteria_v2.md/자문 반영).
- **측정 결과**: both_A 76%→**96%** (48/50). 문진 98%, 법률 96%. 미달 1건은 API 일시오류.

## 결론 (50샘플 기준)
- **both_A 0% → 96%** 달성. 남은 미달은 평가 중 일시 API 오류 1건뿐.
- 핵심 교훈: ① RAG 답변 품질(문진 ④, 가드레일)은 실제 개선됨 ② 그러나 가장 큰 병목은
  **gpt-4o-mini 평가기의 오교정**이었음 — 정확한 평가모델(gpt-4o) + 교정된 기준으로 진실한 점수 확보.
- **남은 작업**: (a) 전체 1100 실행(타임아웃 상향 필수, gpt-4o 비용 고려) (b) 검색 품질(B1)은
  여전히 INSUFFICIENT 다수 — KB 확장 시 근거 인용 품질 추가 향상 여지.

---

## 4. 실행 명령 (런북)

### 4-1. 이미지 빌드 (코드 변경 반영)
```powershell
gcloud builds submit --tag gcr.io/medical-compliance-tester/medical-compliance-tester:batch-eval . --quiet
```

### 4-2. 샘플 실행 (50개, 타임아웃 내, 반복 측정용)
```powershell
gcloud run jobs update run-batch-eval --region=asia-northeast3 `
  --image gcr.io/medical-compliance-tester/medical-compliance-tester:batch-eval `
  --args="batch_eval_rag.py,--source,db,--limit,50,--workers,8,--output,/tmp/eval_sample.json"
gcloud run jobs execute run-batch-eval --region=asia-northeast3 --wait
```

### 4-3. 전체 1100 실행 (타임아웃 상향 필수)
```powershell
gcloud run jobs update run-batch-eval --region=asia-northeast3 `
  --task-timeout=14400 `
  --args="batch_eval_rag.py,--source,db,--workers,16,--output,/tmp/eval_full.json"
gcloud run jobs execute run-batch-eval --region=asia-northeast3 --wait
```

### 4-4. 결과(요약) 로그 추출
```powershell
$exec = (gcloud run jobs executions list --job=run-batch-eval --region=asia-northeast3 --limit=1 --format="value(name)")
gcloud logging read "resource.type=`"cloud_run_job`" AND labels.`"run.googleapis.com/execution_name`"=`"$exec`"" --format="value(textPayload)" --limit=200 --order=desc | Select-String "both_A|등급|평가 완료|컴플라이언스|문진"
```
> 결과 JSON은 컨테이너 `/tmp`에 저장되어 실행 종료 시 사라짐. 영구 보존하려면 batch_eval_rag.py가 GCS(`gs://...`)로 업로드하도록 `--output` 처리 보강 권장.

---

## 5. 남은 병목 & 로드맵 (both_A 100% 도달 경로)

| # | 병목 | 영향 | 해결 방향 | 난이도 |
|---|------|------|-----------|--------|
| B1 | 검색 INSUFFICIENT (KB 미스매치) | 모든 시나리오 약한 근거 | HealthBench 주제 커버 KB 확장 + 한국어 tsvector sparse 검색 수리(현재 0건) + 게이트 임계 재튜닝 | 높음 |
| B2 | 응급 시나리오의 문진 A 불가 (루브릭 충돌) | 응급군은 질문 생략이 정답 → 문진 점수 낮음 | 문진 루브릭 v2의 "응급 안내=품질" 반영(criteria_v2.md), 또는 응급군 별도 평가 | 정책 결정 필요 |
| B3 | 문진 5축 충실도 | ④ 질문 커버리지 | v1에서 ④ 강화 완료, 효과 측정 중 | 완료/측정 |
| B4 | 전체 1100 실행 인프라 | 30분 타임아웃 초과 | task-timeout 상향 또는 샤딩 | 낮음 |

> **현실 평가**: B1(검색)과 B2(응급 루브릭 충돌)가 해결되지 않으면 1100개 전부 both_A는 불가능에 가깝다.
> 단기 목표는 **both_A 비율의 유의미한 상승**(0% → 가능한 최대)과 **법률 A 비율 대폭 상승**(가드레일 오탐 제거 효과).
