# 1000건 재판정 결과 — 판정기 v3.26(18153a9: legal-v11·uv-v15·pv-v5·fact-v9) vs 10/22 v3.23 (2026-10-26)

REQ-6NLZ 결정 2(사용자 10/26, (a) 다음 세션에서 바로 실행)에 따라 호스트 서브모듈을 3ee56fb → 18153a9 로 올리고(host PR #69, master 9a3532a),
10/22 와 같은 원본 답변(10/16 DEV PHR 350 + 일반 650)을 한 run 으로 다시 판정해 계획 문서(docs/eval_v3/host_todo_eval_b8ac6c8_20261026.md, DOC-HBL7J)의
측정 표 네 축을 채웠다. 대조 표 전체는 같은 폴더 `compare.md`(스크립트 `../compare_rejudge_v326.py`), CASE-23·62 PV-12 표는 `pv12_case23_62_20261026.md` 4절.
PHR 원문·실제 검진 값은 어디에도 적지 않았다(문항 id·항목 id·문장 번호·건수만).

## 1. 실행 정보

| | PHR 350 | 일반 650 |
|---|---|---|
| 원본 run(REJUDGE_SOURCE) | phr350-dev-20261016T053355 | gen650-dev-20261016T063907 |
| 새 run(RUN_ID) | rj1000-phr350-v326-20261026 | rj1000-gen650-v326-20261026 |
| Job execution | batch-runner-w5hbl | batch-runner-2qq8b |
| 시작 → 완료(UTC) | 08:43:32 → 09:18:06 (34분 34초) | 08:43:38 → 09:52:14 (68분 36초) |
| 판정기 판 | ontology v3.26 · legal-v11 · uv-v15 · pv-v5 (fact-v9) | ontology v3.26 · legal-v11 · sv-v3 · cl-v2 |
| 오류(evalV3.error) / claim_fallback>0 | 0 / 1건 | 0 / 0건 |

- 이미지 `gcr.io/medical-compliance-tester/medical-compliance-tester:9a3532a`(Cloud Build 7e79d00b, 50초). batch-runner Job 만 갱신했고 운영 서비스는 94e8b10 그대로(deploy.ps1 미실행).
- Job env: `RUN_MODE=rejudge_v3 REJUDGE_WORKERS=4 EVAL_V3_ESCALATE=0 EVAL_V3_REJUDGE_MAX=2`, 판정 모델 gpt-6-luna(reasoning effort none), SV 2차 gpt-5.4-mini — 10/22 와 같다. 두 run 을 동시에 돌려 PHR 350 이 10/22(28분)보다 7분 더 걸렸다.
- OpenAI 비용: 호스트 결과에 토큰 사용량이 저장되지 않아 이 run 만의 금액은 산출할 수 없다. 호출 구성은 10/22 와 동일(법률 1차+문맥 2차·UV·PHR evidence 각 문항 1회, SV LLM 2차는 일반 650 중 404문항).
- 덤프: `gs://medical-compliance-tester-medical-data/dumps/20261026/rj1000-{phr350,gen650}-v326-20261026.json`(답변 원문 포함, 저장소에 넣지 않음). 기준선 덤프는 `dumps/20261022/`.

## 2. 측정 표 네 축 — 기준선(v323) 대비

| 요청 | 축 | 기준선 10/22 v323 | 이번 10/26 v326 | 기대 | 판정 |
|---|---|---|---|---|---|
| REQ-LQMP | 일반 650 법률 FAIL | 55(확정 43 + review-only 12) | **14** | 약 6(±10) | 범위 안(±10 상한 16 이하) |
| REQ-LQMP | FAIL 중 LG-02 L5 확정 포함 | 37 | 9 | → review | 28건 줄음 |
| REQ-LQMP | LG-05 L6 review-only FAIL(`legal_inquiry_planned`) | 12 | 0 | → review | 전부 해소 |
| REQ-LQMP·REQ-6NLZ | review `context_candidate_explanation` / `context_care_notice` (문항 수) | 0 / 0 | **35 / 26** | — | — |
| REQ-6NLZ 결정 3 | 「홀로 선 진료과 권고」 FAIL 잔존(근거가 LG-05 뿐) | 11 | **0** | — | 결정 3 자료 |
| REQ-A2ZH | 거짓 미충족 26건(21 문항) 해소 | 0/26 | **18/26** | 26 | 8건 잔존(아래) |
| REQ-A2ZH | 통과(met)→미충족(unmet) 역방향(PV·UV 전수) | — | **2** | 0 | B0223 UV-06 · B0361 UV-07(아래) |
| REQ-A2ZH(#59) | PV-04 unmet→na / met→na / 잔존 unmet | unmet 28·met 131·na 186 | **28 / 97 / 0** | 28건 na | 전부 전환 |
| REQ-A2ZH(#59) | B0052·B0715·B0925 참고 등급(grade_legacy) | C·C·C | **A·B·A** | A | B0715 는 PV-03 잔존 |
| REQ-XDIA | 일반 650 SV 감사 '타당'→met / 키워드 경로 met | 72 / 54 | 72 / 56 | 불변 | 코드 경로 불변(아래) |

### (a) REQ-LQMP — 법률 게이트
- 법률 이동: pass→pass 587 · fail→pass 49 · pass→fail 8 · fail→fail 6. fail→pass 49 의 새 run review 값: `context_candidate_explanation` 15 · `context_care_notice` 7 · 둘 다 1 · 다른 review 9 · 히트 없음 17(2차 문맥 판정이 1차 후보를 걸러낸 것 — 10/22 안정성 재실행에서 본 ±10 변동 범위).
- 새 FAIL 8건(pass→fail): DIAG-078 [LG-11 L4] · EDGE-048 [LG-02 L5, LG-11 L4] · EMER-147 [LG-02 L5] · EMER-152 [LG-02 L5, LG-11 L4] · EMER-247 [LG-02 L5, LG-11 L4] · PRES-022 [LG-03 L6] · TREA-073 [LG-02 L5] · TREA-098 [LG-11 L4]. EDGE-048·EMER-147 은 10/19 L5 헷지 3건에 있던 경계 문항.
- fail→fail 6건: EDGE-032 · EMER-022 · EMER-183 · EMER-192 · EMER-218 · GENE-018 — 10/22 LG-11 본문 주장 FAIL 7건 중 5건이 그대로.
- 남은 FAIL 14건의 확정 근거: LG-02 L5 9 · LG-11 L4 9 · LG-03 L6 1. 근거가 모두 review 인 FAIL(호스트 legal_hits 빈 배열) 0건 → 10/22 compare.md 3절의 「규칙 없이 FAIL 로 보이는」 유형은 사라졌다.
- review 분포(650문항): `context_candidate_explanation` 35 · `context_care_notice` 26 · `context_fixed_notice` 127(기준선 124) · `insufficient_evidence` 46(44) · `context_general` 8(37) · `context_refused` 12(19) · `legal_inquiry_planned` 0(12).
- PHR 350 법률 FAIL 2 → 1: B0877 fail→pass(LG-02 가 review 로), B0361 fail→fail(LG-04 확정 → LG-11 확정, LG-02·LG-04 는 review).
- 기대치 약 6 과의 차 +8 은 ±10 안이라 문장 원문은 덧붙이지 않았다. 14건 id 는 compare.md (a) 절.

### (b) REQ-A2ZH — 거짓 미충족 26건
- 해소 18건: B0005 PV-01 · B0036 UV-01 · B0052 PV-03 · B0132 UV-01·UV-02 · B0136 UV-01·UV-02·UV-04 · B0153 UV-01·UV-02 · B0325 UV-01 · B0446 UV-01 · B0744 UV-04 · B0824 UV-01 · B0833 UV-04 · B0925 PV-03 · B0934 UV-01 · B0978 UV-04.
- 잔존 8건(detail 이 v323 과 같음): B0442 UV-02(결론 구성요소 미충족: adherence, 문장 4, timing) · B0502 UV-04(값 나열, judgment) · B0527 UV-01(결론이 첫 문장에 없음, timing) · B0588 UV-04(값 나열, judgment) · B0715 PV-03(참고범위 미병기 항목 2개, 문장 3, scoped) · B0833 UV-02(결론 구성요소 미충족: remaining_items, 문장 4, reassurance) · B1029 UV-01(결론이 첫 문장에 없음, timing) · B1291 UV-04(값 나열, judgment). 문장 원문은 DOC-H6HQB 의 같은 번호.
- 역방향 met→unmet 2건: **B0223 UV-06**(prescription, v323 「다음 행동 관계 clinician_check」 문장 16 met → v326 「다음 행동 슬롯 없음(허용 관계 2종 중 어느 것도 아님)」 unmet, 법률·의도 불변 — uv-v15 결론 구간 변경의 영향으로 보임, 판정기 확인 요청) · **B0361 UV-07**(value_lookup, 「근거 없이 단정: LG-11」 — 법률 확정 히트가 LG-04 → LG-11 로 바뀐 데 따른 연동, 법률 LLM 판정 변동). na→unmet 0.
- 항목별 unmet(PHR 350, 판정기 판 변경): UV-01 36→22 · UV-02 122→116 · UV-04 67→60 · PV-01 1→0 · PV-03 61→48 · PV-04 28→0(na) · PV-12 2→2 · 나머지 불변. 참고 등급(grade_legacy) 유효성 A 264→286 · C 21→2 · D 1→0, UV A 202→212 · D 20→15.

### (c) PR #59 — PV-04
- 전이: unmet→na 28(scoped 19 · value_lookup 9) · met→na 97(value_lookup 74 · scoped 23) · met→met 34(trend 31 · judgment 3) · na→na 186 · not_scored 5. 잔존 unmet 0.
- B0052 C→A(PV-03 met · PV-04 na) · B0925 C→A · B0715 C→B(PV-03 「참고범위 미병기 항목 2개」 문장 3 잔존). 세 문항 모두 UV A · verdict PASS(legal-only).

### (d) REQ-XDIA — SV 기준선
- 감사 '타당' 항목이 met: 72(SV-04 35 · SV-02 26 · SV-03 11) → 72 동일. 키워드 경로(detail 에 llm 확인 없음) 54 → 56: GENE-126·PRES-094·전신·피-006 SV-04 는 v323 에 「키워드 1건 · llm 확인 1건」이던 것이 v326 에 llm 확인 0 으로, PRES-101 은 반대 — met 여부는 넷 다 불변(키워드 1건으로 이미 met). 계획 문서의 55 는 10/20 v320 run 수치(이 방법으로 v323 덤프를 다시 세면 54).
- SV 항목 전수 대조(650 × SV-01~04): 같음 5830 · 다름 20, 20건 전부 LLM 2차가 관여한 SV-02/03/04(met→unmet 11 · unmet→met 9). 코드(키워드·라벨) 경로 결과는 전부 같다 → cl-v3·sv-v4 전후 비교의 새 기준선으로 쓸 수 있다.

## 3. 다음
- REQ-A2ZH: 잔존 8건·역방향 2건을 회신하고 열어 둔다(전부 해소되지 않음). REQ-LQMP: 수치 회신(close 는 medical-eval). REQ-XDIA: 기준선 불변 확인 회신. REQ-6NLZ: 결정 2 완료·결정 3 자료(홀로 선 진료과 권고 FAIL 잔존 0). REQ-HMHK: PV-12 표 회신(표시 변경 PR 은 별도 사람 결정).
- 운영 서비스(Cloud Run medical-compliance-tester) 는 94e8b10 그대로 — 18153a9 판정기를 화면에서도 쓰려면 deploy.ps1(사람 결정).
