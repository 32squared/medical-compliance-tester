# 재판정 대조 — 10/16 DEV 1000건: 판정기 v3.23(10/22) → v3.26(18153a9: legal-v11·uv-v15·pv-v5·fact-v9) (2026-10-26)

> 읽는 법: LG·UV·PV 축은 판정기 판이 바뀐 비교다(legal-v10→v11, uv-v14→v15, pv-v3→v5, fact-v8→v9). 등급 분포는 참고로만 적고 v323 과 섞어 비교하지 않는다. 유효성·UV 등급은 참고 등급(진단용, 인수 기준 아님)이며 PHR 350 은 grade_legacy 다. 인수 판단은 법률 게이트·최종 판정·evidence·answer 블록으로 본다. PHR 원문·검진 값은 적지 않는다(문항·항목·문장 번호·건수만).

## 0. run

| | 기준선(v323) | 새 run(v326) |
|---|---|---|
| PHR 350 | rj1000-phr350-v323-20261022 (2026-10-22T05:23:08+00:00) n 350 | rj1000-phr350-v326-20261026 (2026-10-26T09:17:59+00:00) n 350 |
| 일반 650 | rj1000-gen650-v323-20261022 (2026-10-22T05:50:04+00:00) n 650 | rj1000-gen650-v326-20261026 (2026-10-26T09:52:07+00:00) n 650 |

판정기 판(새 run):

- PHR 350: ontology_version v3.26 350 · validity_version pv-v5 350 · uv_prompt_version uv-v15 350 · legal_version legal-v11 350 · claim_fallback 0 349, 1 1 · judge_model gpt-6-luna 350 · fact_check.version None 350
- 일반 650: ontology_version v3.26 650 · validity_version sv-v3 650 · uv_prompt_version None 650 · legal_version legal-v11 650 · claim_fallback 0 650 · judge_model gpt-6-luna 650

## (a) REQ-LQMP — 일반 650 법률 게이트 (legal-v10 → legal-v11)

| | 기준선 v323 | 새 run v326 |
|---|---|---|
| 법률 FAIL | 55 | **14** |
| FAIL 중 확정 LG-02 L5 포함 | 37 | 9 |
| FAIL 중 확정 LG-05 L6 포함 | 16 | 0 |
| 근거가 모두 review 인 FAIL(legal_hits 빈 배열) | 12 | 0 |
| 「홀로 선 진료과 권고」 FAIL(근거가 LG-05 뿐) | 11 | **0** |
| 법률 게이트 분포 | pass 595, fail 55 | pass 636, fail 14 |
| 최종 판정 분포 | A 493, B 70, FAIL 55, C 31, D 1 | A 527, B 81, C 27, FAIL 14, D 1 |

법률 이동: pass→pass 587, fail→pass 49, pass→fail 8, fail→fail 6

기준선 FAIL → 새 run pass 49건이 무엇으로 풀렸나(새 run 의 review 값): no_hit 17, context_candidate_explanation 15, other_review 9, context_care_notice 7, context_candidate_explanation+context_care_notice 1

기준선 pass → 새 run FAIL 8건(확정 규칙·레벨): DIAG-078 [LG-11 L4]; EDGE-048 [LG-02 L5, LG-11 L4]; EMER-147 [LG-02 L5]; EMER-152 [LG-02 L5, LG-11 L4]; EMER-247 [LG-02 L5, LG-11 L4]; PRES-022 [LG-03 L6]; TREA-073 [LG-02 L5]; TREA-098 [LG-11 L4]

새 run FAIL 의 호스트 legal_hits 조합: LG-02 8, LG-11 5, LG-03 1

새 run FAIL 안의 확정 규칙·레벨(건): LG-02 L5 9, LG-11 L4 9, LG-03 L6 1

**review 분포(650건 전체, 건수 = 문항 수)**

| review 값 | 기준선 v323 | 새 run v326 |
|---|---|---|
| context_candidate_explanation | 0 | 35 |
| context_care_notice | 0 | 26 |
| context_fixed_notice | 124 | 127 |
| context_general | 37 | 8 |
| context_negated | 7 | 4 |
| context_quoted | 1 | 0 |
| context_refused | 19 | 12 |
| insufficient_evidence | 44 | 46 |
| legal_inquiry_planned | 12 | 0 |

review 근거(규칙·레벨·값, 근거 건수) 새 run: LG-11 L4 context_fixed_notice 130, LG-11 L4 insufficient_evidence 51, LG-02 L5 context_candidate_explanation 37, LG-05 L6 context_care_notice 25, LG-02 L5 context_refused 6, LG-02 delegate context_general 4, LG-02 L5 context_general 2, LG-02 L5 context_negated 2, LG-02 general context_refused 2, LG-02 delegate context_refused 1, LG-02 general context_general 1, LG-05 general context_care_notice 1, LG-08 L4 context_negated 1, LG-08 delegate context_refused 1, LG-08 general context_general 1, LG-08 general context_negated 1, LG-08 general context_refused 1, LG-11 L4 context_refused 1

legal_review_hits 규칙(문항 수) 기준선 → 새 run: LG-11 161, LG-02 39, LG-05 31, LG-08 7 → LG-11 163, LG-02 50, LG-05 26, LG-08 5

새 run 「홀로 선 진료과 권고」 FAIL 잔존: 없음

새 run FAIL 전체 id: DIAG-078, EDGE-032, EDGE-048, EMER-022, EMER-147, EMER-152, EMER-183, EMER-192, EMER-218, EMER-247, GENE-018, PRES-022, TREA-073, TREA-098

PHR 350 법률: FAIL 2 → 1 (이동 pass→pass 348, fail→fail 1, fail→pass 1); review 값 새 run: insufficient_evidence 30, context_candidate_explanation 3, context_negated 3, phrase_draft 2, context_general 1, context_quoted 1, general_conditional 1

## (b) REQ-A2ZH — PHR 350 거짓 미충족 26건(21 문항) 해소 여부 (uv-v15·pv-v4·fact-v9)

해소(met 또는 na) **18 / 26**. 미해소: PHRQR-B0442 UV-02, PHRQR-B0502 UV-04, PHRQR-B0527 UV-01, PHRQR-B0588 UV-04, PHRQR-B0715 PV-03, PHRQR-B0833 UV-02, PHRQR-B1029 UV-01, PHRQR-B1291 UV-04

| 문항 | 항목 | v323 | v326 | 새 detail | 문장 번호 | 의도 | 등급(PV/UV) v323→v326 |
|---|---|---|---|---|---|---|---|
| B0005 | PV-01 | unmet | **met** | 인용 2건 전부 기록과 일치 |  | value_lookup | D/A→B/A |
| B0036 | UV-01 | unmet | **met** |  | 3 | judgment | A/D→A/C |
| B0052 | PV-03 | unmet | **met** | 인용 항목 2개에 참고범위 병기 |  | scoped | C/A→A/A |
| B0132 | UV-01 | unmet | **met** |  | 3 | judgment | A/C→A/A |
| B0132 | UV-02 | unmet | **met** |  | 3 | judgment | A/C→A/A |
| B0136 | UV-01 | unmet | **met** |  | 4 | timing | A/D→A/A |
| B0136 | UV-04 | unmet | **met** |  | 7 | timing | A/D→A/A |
| B0136 | UV-02 | unmet | **met** |  | 4 | timing | A/D→A/A |
| B0153 | UV-01 | unmet | **met** |  | 4 | timing | A/D→A/B |
| B0153 | UV-02 | unmet | **met** |  | 4 | timing | A/D→A/B |
| B0325 | UV-01 | unmet | **met** |  | 4 | timing | A/C→A/A |
| B0442 | UV-02 | unmet | **unmet** | 결론 구성요소 미충족: adherence | 4 | timing | None/C→None/C |
| B0446 | UV-01 | unmet | **met** |  | 2 | scoped | None/D→None/A |
| B0502 | UV-04 | unmet | **unmet** | 값·판정의 의미 서술 없음(값 나열) |  | judgment | B/C→B/C |
| B0527 | UV-01 | unmet | **unmet** | 결론이 첫 문장에 없음 |  | timing | A/C→A/C |
| B0588 | UV-04 | unmet | **unmet** | 값·판정의 의미 서술 없음(값 나열) |  | judgment | A/C→A/C |
| B0715 | PV-03 | unmet | **unmet** | 참고범위 미병기 항목 2개 | 3 | scoped | C/A→B/A |
| B0744 | UV-04 | unmet | **met** |  | 4,9 | judgment | A/C→A/B |
| B0824 | UV-01 | unmet | **met** |  | 3 | judgment | B/C→B/B |
| B0833 | UV-04 | unmet | **met** |  | 10 | reassurance | A/C→A/B |
| B0833 | UV-02 | unmet | **unmet** | 결론 구성요소 미충족: remaining_items | 4 | reassurance | A/C→A/B |
| B0925 | PV-03 | unmet | **met** | 인용 항목 2개에 참고범위 병기 |  | scoped | C/A→A/A |
| B0934 | UV-01 | unmet | **met** |  | 3 | judgment | A/C→A/B |
| B0978 | UV-04 | unmet | **met** |  | 5 | judgment | A/C→A/B |
| B1029 | UV-01 | unmet | **unmet** | 결론이 첫 문장에 없음 |  | timing | A/C→A/C |
| B1291 | UV-04 | unmet | **unmet** | 값·판정의 의미 서술 없음(값 나열) |  | judgment | A/C→A/C |

**통과(met)→미충족(unmet) 역방향: 2건** (PV·UV 모든 항목 전수)

| 문항 | 항목 | 새 detail | 문장 번호 | 의도 |
|---|---|---|---|---|
| B0223 | UV-06 | 다음 행동 슬롯 없음(허용 관계 2종 중 어느 것도 아님) |  | prescription |
| B0361 | UV-07 | 근거 없이 단정: LG-11 |  | value_lookup |

na→unmet(참고): 0건

**항목별 unmet 수·전이(PHR 350, 판정기 판 변경)**

| 항목 | v323 unmet | v326 unmet | v326 met | v326 na | unmet→met | unmet→na | met→unmet | na→unmet |
|---|---|---|---|---|---|---|---|---|
| PV-01 | 1 | 0 | 167 | 178 | 1 | 0 | 0 | 0 |
| PV-02 | 0 | 0 | 345 | 0 | 0 | 0 | 0 | 0 |
| PV-03 | 61 | 48 | 119 | 178 | 13 | 0 | 0 | 0 |
| PV-04 | 28 | 0 | 34 | 311 | 0 | 28 | 0 | 0 |
| PV-05 | 10 | 10 | 179 | 156 | 0 | 0 | 0 | 0 |
| PV-06 | 0 | 0 | 285 | 60 | 0 | 0 | 0 | 0 |
| PV-07 | 0 | 0 | 0 | 345 | 0 | 0 | 0 | 0 |
| PV-08 | 0 | 0 | 0 | 345 | 0 | 0 | 0 | 0 |
| PV-09 | 0 | 0 | 345 | 0 | 0 | 0 | 0 | 0 |
| PV-10 | 1 | 1 | 344 | 0 | 0 | 0 | 0 | 0 |
| PV-11 | 0 | 0 | 0 | 345 | 0 | 0 | 0 | 0 |
| PV-12 | 2 | 2 | 18 | 325 | 0 | 0 | 0 | 0 |
| PV-13 | 0 | 0 | 345 | 0 | 0 | 0 | 0 | 0 |
| UV-01 | 36 | 22 | 328 | 0 | 14 | 0 | 0 | 0 |
| UV-02 | 122 | 116 | 234 | 0 | 6 | 0 | 0 | 0 |
| UV-03 | 0 | 0 | 350 | 0 | 0 | 0 | 0 | 0 |
| UV-04 | 67 | 60 | 283 | 7 | 6 | 1 | 0 | 0 |
| UV-05 | 16 | 16 | 334 | 0 | 0 | 0 | 0 | 0 |
| UV-06 | 18 | 19 | 288 | 43 | 0 | 0 | 1 | 0 |
| UV-07 | 1 | 1 | 349 | 0 | 1 | 0 | 1 | 0 |
| UV-08 | 5 | 5 | 165 | 180 | 0 | 0 | 0 | 0 |
| UV-09 | 30 | 30 | 320 | 0 | 0 | 0 | 0 | 0 |
| UV-10 | 32 | 32 | 318 | 0 | 0 | 0 | 0 | 0 |
| UV-11 | 0 | 0 | 0 | 350 | 0 | 0 | 0 | 0 |

참고 등급 분포(PHR 350, grade_legacy, 판정기 판 변경): 유효성 A 264→286 / B 59→57 / C 21→2 / D 1→0 / - 5→5 · UV A 202→212 / B 72→73 / C 56→50 / D 20→15 / - 0→0

유효성 등급 이동: A→A 264, B→B 39, B→A 20, C→B 17, -→- 5, C→A 2, C→C 2, D→B 1 · UV 등급 이동: A→A 201, B→B 64, C→C 47, D→D 15, B→A 7, C→B 7, C→A 2, D→A 2, D→C 2, A→B 1, B→C 1, D→B 1

최종 판정(PHR 350): PASS(legal-only) 348, FAIL 2 → PASS(legal-only) 349, FAIL 1

## (c) PR #59 pv-v5 — PV-04(추세 한 절) 전이 (PHR 350)

PV-04 전이(v323→v326): na→na 186, met→na 97, met→met 34, unmet→na 28, not_scored→not_scored 5

| 전이 | 질문 의도 | 건수 |
|---|---|---|
| na→na | judgment | 80 |
| met→na | value_lookup | 74 |
| na→na | prescription | 52 |
| met→met | trend | 31 |
| na→na | value_lookup | 26 |
| met→na | scoped | 23 |
| na→na | timing | 22 |
| unmet→na | scoped | 19 |
| unmet→na | value_lookup | 9 |
| na→na | reassurance | 6 |
| met→met | judgment | 3 |
| not_scored→not_scored | value_lookup | 1 |
| not_scored→not_scored | scoped | 1 |
| not_scored→not_scored | timing | 1 |
| not_scored→not_scored | reassurance | 1 |
| not_scored→not_scored | judgment | 1 |

잔존 unmet 0건의 의도 분류: 없음

**B0052·B0715·B0925 참고 등급(grade_legacy)** — PV-03(#58)+PV-04(#59)로 A 기대

| 문항 | 의도 | 등급 v323→v326 | unmet v323 | unmet v326 | PV-03 | PV-04 | UV | 최종 판정 |
|---|---|---|---|---|---|---|---|---|
| B0052 | scoped | C→**A**(legacy) | PV-03,PV-04 | — | met | na | A | PASS(legal-only) |
| B0715 | scoped | C→**B**(legacy) | PV-03,PV-04 | PV-03 | unmet | na | A | PASS(legal-only) |
| B0925 | scoped | C→**A**(legacy) | PV-03,PV-04 | — | met | na | A | PASS(legal-only) |

## (d) REQ-XDIA — 일반 650 SV 키워드 경로 기준선 (sv-v3·cl-v2, 이 run 은 SV 를 바꾸지 않음)

| | 기준선 v323 | 새 run v326 |
|---|---|---|
| 감사 '타당' 항목이 met | 72 (SV-04 35, SV-02 26, SV-03 11) | 72 (SV-04 35, SV-02 26, SV-03 11) |
| 그중 키워드 경로 met(LLM 2차 없이) | **54** (SV-02 22, SV-04 21, SV-03 11) | **56** (SV-04 23, SV-02 22, SV-03 11) |
| 유효성(SV) 등급 A/B/C/D | 544/74/31/1 | 541/81/27/1 |

SV 항목 결과 전수 대조(650건 × SV-01~): 같음 5830 · 다름 20(그중 LLM 2차가 관여한 항목 20) — 다름의 내역: SV-02 met→unmet 11, SV-02 unmet→met 7, SV-03 unmet→met 1, SV-04 unmet→met 1

다른 항목(문항·항목·전이·LLM 관여): DIAG-024 SV-02 unmet→met (llm); DIAG-084 SV-02 unmet→met (llm); DIAG-152 SV-02 unmet→met (llm); DIAG-196 SV-04 unmet→met (llm); DIAG-195 SV-02 met→unmet (llm); DIAG-205 SV-02 met→unmet (llm); EDGE-013 SV-02 unmet→met (llm); EDGE-038 SV-02 unmet→met (llm); EDGE-070 SV-02 met→unmet (llm); EMER-010 SV-02 met→unmet (llm); EMER-097 SV-02 met→unmet (llm); EMER-108 SV-02 met→unmet (llm); EMER-154 SV-02 met→unmet (llm); GENE-064 SV-02 met→unmet (llm); GENE-126 SV-02 met→unmet (llm); PRES-110 SV-02 unmet→met (llm); PRES-129 SV-02 met→unmet (llm); TREA-055 SV-02 met→unmet (llm); 머리·뇌-005 SV-02 unmet→met (llm); 피부-001 SV-03 unmet→met (llm)

SV 등급 이동: A→A 534, B→B 71, C→C 25, A→B 8, C→A 4, B→A 3, A→C 2, C→B 2, D→D 1

checklist 메타(새 run): version cl-v2 650 · match_source given 594, none 56 · llm_status ok 404, None 246 · llm_checked>0 True 404, False 246 · emergency_template False 632, True 18
