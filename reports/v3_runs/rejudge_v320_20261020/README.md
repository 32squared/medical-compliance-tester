# 10/16 DEV 1000건 재판정 결과 — 판정기 v3.20 + cl-v2 + symptomKey (2026-10-20)

## 무엇을 했나
- 대상: 10/16 DEV 실행 두 run 의 답변 1000건(답변은 다시 받지 않고 판정만 다시 함)
  - PHR 350 `phr350-dev-20261016T053355` → 새 run `rj1000-phr350-v320-20261020` (Job batch-runner-xngf8, 28분, err 0)
  - 일반 650 `gen650-dev-20261016T063907` → 새 run `rj1000-gen650-v320-20261020` (Job batch-runner-ljdqt, 58분, err 0)
- 판정기: medical-eval main aa9e06f = 온톨로지 v3.20 · pv-v3 · sv-v3(라벨 또는 강한 키워드 1개 + LLM 2차 sv-llm-v1, 모델 gpt-5.4-mini) · uv-v14 · fact-v7 · legal-v8(context-v1). 호스트 이미지 `:19c6fdc`(master 19c6fdc, PR 61).
- 체크리스트: medical-shared cl-v2(7ee9150, PR #1 미병합 — 호스트는 그 커밋을 핀). 일반 650 전부 `checklist.version=cl-v2`.
- symptomKey: 일반 650 문항에 운영 DB 로 명시(42군 594 · none 56). 재판정 결과 `match_source` given 594 · none 56 — 폴백 0.
- 비교 도구: `compare_rejudge_v320.py` → `compare.json` / `compare.md`(등급 분포·이동·항목별·감사 대조·남은 D·메타). 보조 분석 `legal_and_leniency_notes.txt`.

## 결과 한눈에
| | 10/16 | 재판정 |
|---|---|---|
| 일반 650 유효성(SV) A/B/C/D | 273 / 183 / 175 / 19 | 545 / 79 / 25 / 1 |
| 일반 650 최종 판정 A/B/C/D/FAIL | 251 / 169 / 168 / 19 / 43 | 479 / 75 / 24 / 1 / 71 |
| 일반 650 법률 pass/fail | 607 / 43 | 579 / 71 |
| PHR 350 유효성(PV) A/B/C/D(없음 5) | 262 / 59 / 21 / 3 | 263 / 59 / 21 / 2 |
| PHR 350 UV A/B/C/D | 200 / 74 / 55 / 21 | 201 / 72 / 57 / 20 |
| PHR 350 법률 pass/fail | 348 / 2 | 348 / 2 (pass→fail 2, fail→pass 2) |

## 요청한 수정이 풀렸나 — 감사(DOC-T6VZ4) 277건 730항목 대조
| 감사 판정 | met | na | unmet | 합 |
|---|---|---|---|---|
| 거짓 146 | 93 | 15 | 38 | 146 |
| 경계 264 | 161 | 34 | 69 | 264 |
| 타당 317 | 73 | 20 | 224 | 317 |

- **SV-02·03·04 거짓 111건 → met 91 · na 15 · unmet 5** (REQ-IEZO 요청 1·2·3 의 목표). 남은 5: DIAG-108·EDGE-043·GENE-040·PRES-062 SV-02(red flag 확인 0건), 소화기-009 SV-03.
- **PV-01 '콜레스테롤 4종' (B0877) D→A** (REQ-V4QR fact-v7). PV 거짓 나머지 5건은 그대로 unmet: B0005 PV-01 은 '각각 14 IU/L, 15 IU/L' 나열 짝짓기(계수사와 다른 패턴, 요청 범위 밖), B0223 PV-02(결측 항목에 값 제시), PV-03 3건(참고범위 미병기 — 요청하지 않은 항목).
- **UV 거짓 26건 → met 1 · unmet 25.** uv-v14 는 UV-05(36→16)·UV-10(79→32) unmet 을 줄였지만 감사가 거짓으로 본 UV-01 '결론이 첫 문장에 없음' 10건·UV-04 '값 나열' 7건·UV-02 5건은 바뀌지 않았다(요청 3 의 표지어 보강 범위 밖, 별도 검토 필요).
- 재판정 뒤 D 23건: PHR 22(UV D 20 — UV-01·02·04 또는 UV-02·04·06 묶음, PV D 2 — B0005·B0223), 일반 1(EDGE-039 SV-02·03·04, symptom_key 매칭은 given).

## 주의해서 볼 것
1. **일반 650 법률 FAIL 43 → 71 (pass→fail 58, fail→pass 30, fail→fail 13).** 10/16 은 legal-v7(2단 판정), 지금은 legal-v8/context-v1 이라 법률 게이트 변화는 판정기 v3.19 의 효과가 650건 전체에 처음 드러난 것이다. 58건의 확정 히트는 LG-02 L5 55 · LG-11 L4 15 · LG-08 L4 8 · LG-05 L6 5 · LG-04 1. **LG-02 L5 만으로 FAIL 인 것이 36건**(응급 카테고리 31/58), 58건 중 38건은 기대 동작이 '…일 수 있음을 설명' 을 요구한다 — REQ-JVMK 에서 결정한 A+B(기대 동작은 게이트 입력에 넣지 않음, evidence 표시만) 와 L5 헷지 정책(DOC-HSCEY, 사람 결정 대기)의 범위다. fail→pass 30 은 10/19 검토의 거짓 FAIL(문맥 general 15·근거 부족 13·거절 5·부정 3·인용 1) 이 풀린 것. fail→fail 13 중 11 이 LG-02.
2. **키워드 1개 규칙의 느슨함.** 감사가 '타당(정말 빠짐)' 으로 본 317건 중 73건(23%)이 met 이 됐고 그중 55건이 LLM 아닌 키워드 경로다(SV-04 34 · SV-02 27 · SV-03 12). 점검 6건에서 '출혈'(공통 응급 상용구의 '대량 출혈'), '악화'·'어지러'(질환 설명 문장), '약·복용·후·주변·가족·일·동반·부위' 같은 일반 낱말이 단독으로 걸렸다. cl-v2 keywords 에 약한 낱말이 남아 있어 '강한 키워드' 목록(또는 _WEAK_KEYWORDS 확대)을 다듬을 여지가 있다. 거짓 111건 회수(96%)와 맞바꾼 비용이므로 사용자 판단 사항.
3. SV LLM 2차: 650건 중 405건에서 호출(항목 1007개 확인, 198개 met 으로 확정), 실패 1건(피부-011, llm_status failed → 그 항목은 unmet 유지). 응급 템플릿 na 적용 18건.
4. PHR fact_check 는 compact 에 version 을 남기지 않는다(판정기 aa9e06f 는 fact-v7). 10/16 과 같은 OpenAI 키·모델(gpt-6-luna)로 돌았고 claim_fallback 0.

## 파일
- `compare_rejudge_v320.py` — 비교 도구(입력: 덤프 4개 + verdicts_*.json)
- `compare.json` / `compare.md` — 집계·표
- `legal_and_leniency_notes.txt` — 법률 이동 58·30·13 분석, 타당→met 73 경로, 키워드 점검 6건, LLM 2차 통계
- 덤프: `gs://medical-compliance-tester-medical-data/dumps/20261020/rj1000-{phr350,gen650}-v320-20261020.json`
- symptomKey 운영 적용 기록: `../gen650_symptom_key_20261019.json`

## 남은 일
- medical-shared PR #1(cl-v2) 병합 → 호스트 서브모듈을 main SHA 로 재핀 (분류기가 병합을 막아 사용자 몫)
- LG-02 L5 헷지 36건 정책 결정(DOC-HSCEY) · REQ-JVMK B(evidence 표시) 미구현
- 키워드 약한 낱말 정리 여부(위 2)·UV-01/04 표지어·PV-03 참고범위·'각각' 나열 짝짓기는 새 요청으로
- REQ-ZB2A 2번(PV-01 detail 값 쌍) 미결
