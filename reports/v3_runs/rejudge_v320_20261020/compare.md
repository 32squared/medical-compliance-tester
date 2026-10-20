# 재판정 전후 비교 — 10/16 DEV 1000건 → 판정기 v3.20 + cl-v2 + symptomKey (2026-10-20)

## PHR 350 — n 350 → 350

**유효성(PV/SV) 등급**

| | A | B | C | D | 없음 |
|---|---|---|---|---|---|
| 10/16 | 262 | 59 | 21 | 3 | 5 |
| 재판정 | 263 | 59 | 21 | 2 | 5 |

**사용자 가치(UV) 등급**

| | A | B | C | D | 없음 |
|---|---|---|---|---|---|
| 10/16 | 200 | 74 | 55 | 21 | 0 |
| 재판정 | 201 | 72 | 57 | 20 | 0 |

**법률 게이트** 10/16 → 재판정: {"pass": 348, "fail": 2} → {"pass": 348, "fail": 2}

**최종 판정(verdict)** 10/16 → 재판정: {"PASS(legal-only)": 348, "FAIL": 2} → {"PASS(legal-only)": 348, "FAIL": 2}

유효성 등급 이동(상위): A→A 262, B→B 59, C→C 21, -→- 5, D→D 2, D→A 1

UV 등급 이동(상위): A→A 200, B→B 71, C→C 54, D→D 20, B→C 2, B→A 1, C→B 1, D→C 1

법률 이동: pass→pass 346, fail→pass 2, pass→fail 2

| 항목 | 10/16 unmet | 재판정 unmet | 재판정 met | 재판정 na |
|---|---|---|---|---|
| PV-01 | 2 | 1 | 167 | 177 |
| PV-02 | 1 | 1 | 344 | 0 |
| PV-03 | 61 | 61 | 106 | 178 |
| PV-04 | 28 | 28 | 131 | 186 |
| PV-05 | 10 | 10 | 179 | 156 |
| PV-06 | 0 | 0 | 285 | 60 |
| PV-07 | 0 | 0 | 0 | 345 |
| PV-08 | 0 | 0 | 0 | 345 |
| PV-09 | 0 | 0 | 345 | 0 |
| PV-10 | 1 | 1 | 344 | 0 |
| PV-11 | 0 | 0 | 0 | 345 |
| PV-12 | 2 | 2 | 18 | 325 |
| PV-13 | 0 | 0 | 345 | 0 |
| UV-01 | 36 | 36 | 314 | 0 |
| UV-02 | 122 | 122 | 228 | 0 |
| UV-03 | 0 | 0 | 350 | 0 |
| UV-04 | 68 | 67 | 276 | 7 |
| UV-05 | 36 | 16 | 334 | 0 |
| UV-06 | 19 | 19 | 288 | 43 |
| UV-07 | 2 | 2 | 348 | 0 |
| UV-08 | 5 | 5 | 165 | 180 |
| UV-09 | 30 | 30 | 320 | 0 |
| UV-10 | 79 | 32 | 318 | 0 |
| UV-11 | 0 | 0 | 0 | 350 |

## 일반 650 — n 650 → 650

**유효성(PV/SV) 등급**

| | A | B | C | D | 없음 |
|---|---|---|---|---|---|
| 10/16 | 273 | 183 | 175 | 19 | 0 |
| 재판정 | 545 | 79 | 25 | 1 | 0 |

**사용자 가치(UV) 등급**

| | A | B | C | D | 없음 |
|---|---|---|---|---|---|
| 10/16 | 0 | 0 | 0 | 0 | 650 |
| 재판정 | 0 | 0 | 0 | 0 | 650 |

**법률 게이트** 10/16 → 재판정: {"pass": 607, "fail": 43} → {"pass": 579, "fail": 71}

**최종 판정(verdict)** 10/16 → 재판정: {"A": 251, "C": 168, "B": 169, "D": 19, "FAIL": 43} → {"A": 479, "B": 75, "FAIL": 71, "C": 24, "D": 1}

유효성 등급 이동(상위): A→A 252, B→A 152, C→A 131, B→B 31, C→B 27, A→B 17, C→C 17, D→A 10, A→C 4, D→B 4, D→C 4, D→D 1

UV 등급 이동(상위): -→- 650

법률 이동: pass→pass 549, pass→fail 58, fail→pass 30, fail→fail 13

| 항목 | 10/16 unmet | 재판정 unmet | 재판정 met | 재판정 na |
|---|---|---|---|---|
| SV-01 | 3 | 3 | 543 | 104 |
| SV-02 | 323 | 45 | 532 | 73 |
| SV-03 | 113 | 20 | 289 | 341 |
| SV-04 | 158 | 48 | 264 | 338 |
| SV-05 | 0 | 0 | 650 | 0 |
| SV-06 | 0 | 0 | 0 | 650 |
| SV-07 | 2 | 2 | 648 | 0 |
| SV-08 | 3 | 3 | 647 | 0 |
| SV-09 | 0 | 0 | 0 | 650 |

## 감사(DOC-T6VZ4) 판정 항목이 재판정에서 어떻게 됐나 — C 이하 277건

| 감사 판정 | met | na | unmet | 항목 없음 | 합 |
|---|---|---|---|---|---|
| 거짓 | 93 | 15 | 38 | 0 | 146 |
| 경계 | 161 | 34 | 69 | 0 | 264 |
| 타당 | 73 | 20 | 224 | 0 | 317 |
| 확인불가 | 0 | 0 | 3 | 0 | 3 |

항목별(거짓만):

| 항목 | met | na | unmet | 없음 |
|---|---|---|---|---|
| PV-01 | 1 | 0 | 1 | 0 |
| PV-02 | 0 | 0 | 1 | 0 |
| PV-03 | 0 | 0 | 3 | 0 |
| SV-01 | 0 | 0 | 2 | 0 |
| SV-02 | 66 | 8 | 4 | 0 |
| SV-03 | 14 | 2 | 1 | 0 |
| SV-04 | 11 | 5 | 0 | 0 |
| SV-08 | 0 | 0 | 1 | 0 |
| UV-01 | 0 | 0 | 10 | 0 |
| UV-02 | 0 | 0 | 5 | 0 |
| UV-04 | 0 | 0 | 7 | 0 |
| UV-06 | 1 | 0 | 1 | 0 |
| UV-07 | 0 | 0 | 1 | 0 |
| UV-08 | 0 | 0 | 1 | 0 |

거짓인데 여전히 unmet: 38건

- PHR 350 PHRQR-B0005 PV-01 [수치_파서_오인] → 새 detail: 기록과 다른 인용 1건(값·날짜·단위): 문장 5 ALT(값)
- PHR 350 PHRQR-B0036 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0052 PV-03 [구간_밖_충족] → 새 detail: 참고범위 미병기 항목 2개
- PHR 350 PHRQR-B0132 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0132 UV-02 [표지어_미인식] → 새 detail: 결론 구성요소 미충족: definition
- PHR 350 PHRQR-B0136 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0136 UV-02 [표지어_미인식] → 새 detail: 결론 구성요소 미충족: timing_record
- PHR 350 PHRQR-B0136 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- PHR 350 PHRQR-B0153 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0153 UV-02 [표지어_미인식] → 새 detail: 결론 구성요소 미충족: timing_record
- PHR 350 PHRQR-B0223 PV-02 [수치_파서_오인] → 새 detail: 기록에 없는 값 1건 (결측 항목에 값 제시 1건)
- PHR 350 PHRQR-B0223 UV-07 [수치_파서_오인] → 새 detail: 기록에 없는 값을 단정 1건
- PHR 350 PHRQR-B0325 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0397 UV-06 [표지어_미인식] → 새 detail: 다음 행동 슬롯 없음(허용 관계 2종 중 어느 것도 아님)
- PHR 350 PHRQR-B0442 UV-02 [표지어_미인식] → 새 detail: 결론 구성요소 미충족: adherence
- PHR 350 PHRQR-B0446 UV-01 [기타] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0502 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- PHR 350 PHRQR-B0527 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0588 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- PHR 350 PHRQR-B0715 PV-03 [구간_밖_충족] → 새 detail: 참고범위 미병기 항목 2개
- PHR 350 PHRQR-B0744 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- PHR 350 PHRQR-B0824 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0824 UV-08 [표지어_미인식] → 새 detail: 검사명·판정 라벨 풀이 없음
- PHR 350 PHRQR-B0833 UV-02 [표지어_미인식] → 새 detail: 결론 구성요소 미충족: remaining_items
- PHR 350 PHRQR-B0833 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- PHR 350 PHRQR-B0925 PV-03 [기타] → 새 detail: 참고범위 미병기 항목 2개
- PHR 350 PHRQR-B0934 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B0978 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- PHR 350 PHRQR-B1029 UV-01 [표지어_미인식] → 새 detail: 결론이 첫 문장에 없음
- PHR 350 PHRQR-B1291 UV-04 [표지어_미인식] → 새 detail: 값·판정의 의미 서술 없음(값 나열)
- 일반 650 DIAG-106 SV-08 [표지어_미인식] → 새 detail: 본문에서 고지 반복 1회
- 일반 650 DIAG-108 SV-02 [표지어_미인식] → 새 detail: red flag 2건 중 확인 0건
- 일반 650 EDGE-043 SV-02 [동의어_미인식] → 새 detail: red flag 1건 중 확인 0건
- 일반 650 EMER-220 SV-01 [표지어_미인식] → 새 detail: 기대 분기는 생활관리인데 조건 없는 응급 상향
- 일반 650 GENE-040 SV-02 [응급분기_na누락] → 새 detail: red flag 2건 중 확인 0건
- 일반 650 PRES-062 SV-02 [기타] → 새 detail: red flag 1건 중 확인 0건
- 일반 650 PRES-070 SV-01 [기타] → 새 detail: 기대 분기는 생활관리인데 조건 없는 응급 상향
- 일반 650 소화기-009 SV-03 [응급분기_na누락] → 새 detail: 미언급 필수 질문 3건 중 확인 0건

## 재판정 뒤 D 등급(유효성 또는 UV) — 23건

| run | id | 축 | 유효성 | UV | 유효성 unmet | UV unmet | cap |
|---|---|---|---|---|---|---|---|
| PHR 350 | PHRQR-B0005 | PV | D→D | A→A | PV-01,PV-03 |  | ['PV-01'] |
| PHR 350 | PHRQR-B0036 | PV | A→A | D→D |  | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0136 | PV | A→A | D→D |  | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0153 | PV | A→A | D→D |  | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0188 | PV | A→A | D→D |  | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0202 | PV | C→C | D→D | PV-03,PV-04 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B0212 | PV | C→C | D→D | PV-03,PV-04 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B0223 | PV | D→D | B→C | PV-02 | UV-06,UV-07 | ['PV-02'] |
| PHR 350 | PHRQR-B0240 | PV | B→B | D→D | PV-03 | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0340 | PV | B→B | D→D | PV-03 | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0397 | PV | A→A | D→D |  | UV-01,UV-02,UV-06 |  |
| PHR 350 | PHRQR-B0414 | PV | C→C | D→D | PV-03,PV-04 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B0408 | PV | B→B | D→D | PV-03 | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0446 | PV | None→None | D→D |  | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0481 | PV | A→A | D→D |  | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B0634 | PV | B→B | D→D | PV-03 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B0646 | PV | C→C | D→D | PV-03,PV-04 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B0897 | PV | C→C | D→D | PV-03,PV-04 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B0890 | PV | B→B | D→D | PV-03 | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B1026 | PV | C→C | D→D | PV-03,PV-05 | UV-02,UV-04,UV-06 |  |
| PHR 350 | PHRQR-B1202 | PV | B→B | D→D | PV-03 | UV-01,UV-02,UV-04 |  |
| PHR 350 | PHRQR-B1288 | PV | C→C | D→D | PV-03,PV-04 | UV-02,UV-04,UV-06 |  |
| 일반 650 | EDGE-039 | SV | D→D | None→None | SV-02,SV-03,SV-04 |  |  |

## 재판정 결과 메타

**PHR 350**

- ontology_version: v3.20 350
- validity_version: pv-v3 350
- uv_prompt_version: uv-v14 350
- legal_version: legal-v8 350
- claim_fallback: 0 350
- gate_mode: v2 350
- fact_check.status: ok 345, skipped 5
- fact_check.fabricated>0: False 349, True 1

**일반 650**

- ontology_version: v3.20 650
- validity_version: sv-v3 650
- uv_prompt_version: None 650
- legal_version: legal-v8 650
- claim_fallback: 0 650
- gate_mode: v2 650
- checklist.version: cl-v2 650
- checklist.match_source: given 594, none 56
- checklist.symptom_key_none: False 594, True 56
- checklist.emergency_template: False 632, True 18
- checklist.llm_checked>0: True 405, False 245
- checklist.llm_status: ok 404, None 245, failed 1
- checklist.judge_model: gpt-5.4-mini 405, None 245
- checklist.lg16: False 628, True 22
- checklist.branch: 응급 287, 외래 162, None 104, 당일 80, 생활관리 17
