# 호스트 할 일 — 판정기 18153a9(legal-v11 + uv-v15·pv-v5·fact-v9) 반영, 1000건 재판정 한 번으로 REQ-LQMP·REQ-A2ZH 측정 (2026-10-26)

> 10/26 14:34 갱신: 올림 대상이 b8ac6c8 → **18153a9**(PR #59, pv-v5)로 바뀌었다. 파일명의 b8ac6c8 은 첫 판 이름이라 그대로 둔다.

REQ-LQMP(medical-eval PR #57, 10/26 10:54 회신)·REQ-A2ZH(PR #58, 10/26 13:52 회신 · PR #59, 14:34 추가 회신) 반영 메모. 자동 처리(dispatch)에서 작성했고 코드·커밋·배포는 하지 않았다.
DOC-호스트 할 일 legal-v10(host_todo_legal_v10_frame_20261021.md)의 '서브모듈 3ee56fb 올림' 은 끝났고(host PR #63), 이 문서의 올림이 그 다음이다.

## medical-eval 쪽에서 끝난 것 (gh 로 10/26 확인)
| PR | 병합(UTC) | main | 판 | 바뀐 축 |
|---|---|---|---|---|
| #57 | 2026-10-26 01:53 | 9b9cddf | legal-v11 · 온톨로지 v3.24 · 연동 규격 v0.5.26 | LG-02·LG-04·LG-05 후보를 코드 선판정 review `context_candidate_explanation`·`context_care_notice`(WEAK) — LG 기준선 무효 |
| #58 | 2026-10-26 04:51 | b8ac6c8 | uv-v15 · pv-v4 · fact-v9 · 온톨로지 v3.25 · 연동 규격 v0.5.27 | UV-01·02·04, PV-01·03, grade_legacy 가 미충족→충족 방향만 — UV·PV 회귀 기준선 무효. LG·SV 불변, 결과 구조·kind 값 불변 |
| #59 | 2026-10-26 05:32 | **18153a9** | pv-v5 · 온톨로지 v3.26 · 연동 규격 v0.5.28 (uv-v15·fact-v9 그대로) | 질문 의도가 범위 한정(scoped, 「…만 알려·보여·말해·확인」「그것만」)·값 조회(value_lookup, 「수치·값·얼마·최근」, 결측 문의 포함)이면 PV-04 를 na(detail 「질문 의도 〈의도〉 — 추세 서술을 요구하지 않음」). 의도 분류는 PV-05 예외와 같은 코드. LG·SV·UV·fact_check·evidence·answer 불변, PV-04·grade_legacy 만 미충족→na. REQ-NIAR 「가」(10/26) 반영 |

- 계보(gh 10/26 14시 이후 확인): `compare 3ee56fb...b8ac6c8` ahead 5 / behind 0, `9b9cddf...b8ac6c8` ahead 3 / behind 0, `b8ac6c8...18153a9` ahead 2 / behind 0 — 18153a9 가 세 PR 을 모두 포함한다. 서브모듈은 **한 번에 18153a9** 로 올린다(9b9cddf·b8ac6c8 중간 올림 불필요).
- #59 검증(medical-eval 회신): pytest 6195 passed·46 xfailed·0 failed(로컬, CI 없음), export_snapshot --check OK, 골든 oracle main 대비 동일, eval_set 11건 코드 전용 대조 변화 1건(E01 PV-04 met→na, value_lookup).
- #58 검증(medical-eval 회신): pytest 6183 passed·46 xfailed, export_snapshot --check OK, 골든 eval_set 11건 코드 전용 PV·UV main 대비 변화 0, 거짓 unmet 0. 테스트 `tests/test_uv_v15_pv_v4_fact_v9.py` 32건.
- #58 의 코드 상수 정의 표지 「란 」은 「교란은」「호흡곤란 등」에 걸려 뺐다(골든 3건 거짓 충족 확인) — UV-04 정의 표지는 온톨로지 `definition_marker` 15행(이란·뜻합니다·라는 뜻·검진 구분·뜻으로·의미로·쓰이는 표현·쓰입니다)과 코드 「세포·소견이 관찰」「…에서 관찰」(「경과 관찰」 제외).

## 호스트가 할 일 (사람이 여는 세션에서 — 커밋·배포·Job 실행이 필요)
> 10/26 17:4x 실행(사람 세션, REQ-6NLZ 결정 2 = (a)): 1 = host PR #69 병합 → origin/master **9a3532a**(packages/medical_eval 18153a9, 호스트 판정 테스트 85 passed, CI host-lint·host-pytest 통과) · 2 = Job 이미지 `gcr.io/medical-compliance-tester/medical-compliance-tester:9a3532a` 빌드(Cloud Build 7e79d00b, 50초) → batch-runner 갱신(운영 서비스는 94e8b10 그대로, deploy.ps1 미실행) · 3 = `rj1000-phr350-v326-20261026`(batch-runner-w5hbl) · `rj1000-gen650-v326-20261026`(batch-runner-2qq8b) 08:43Z 시작, REJUDGE_WORKERS=4 · EVAL_V3_ESCALATE=0 · EVAL_V3_REJUDGE_MAX=2 · 4 = 변경 없음 확인(v0.5.26~28 diff 대조). 결과·대조는 `reports/v3_runs/rj1000_v326_20261026/compare.md`(스크립트 `compare_rejudge_v326.py`).
1. `packages/medical_eval` 서브모듈 **3ee56fb → 18153a9** 올림 PR(host PR #63 과 같은 꼴). `packages/medical_shared` 는 7ee9150(cl-v2) 유지 — cl-v3(REQ-XDIA)는 아직 PR 없음(10/26 14시 기준 medical-shared PR #1 이 마지막). 호스트 판정 테스트 78건 통과 확인 뒤 병합.
2. Job 이미지 재빌드(deploy 스크립트, 운영 계열 master).
3. 재판정 run: `RUN_MODE=rejudge_v3`, 10/22 와 같은 원본 답변(PHR 350 + 일반 650, `REJUDGE_SOURCE` 는 rj1000_v323_20261022 run 과 동일), 새 RUN_ID 예 `rj1000-phr350-v326-<날짜>` · `rj1000-gen650-v326-<날짜>`(온톨로지 v3.26 기준). 10/22 는 650건 약 1시간.
4. 호스트 코드 변경 없음 — review 두 값·evidence kind=form(v0.5.26)은 표시기가 알려지지 않은 값을 그대로 보여 주고, v0.5.27·v0.5.28 은 구조·kind 값 불변(PV-04 na 는 이미 쓰이는 상태값).

## 한 run 에서 측정할 것 (기준선 = rj1000-*-v323-20261022, 결과 DOC-W75D7, compare.md)
| 요청 | 축 | 기준선(10/22 v323) | 기대 | 회신할 곳 |
|---|---|---|---|---|
| REQ-LQMP | 일반 650 법률 FAIL | 55(확정 43 + review-only 12), LG-02 L5 FAIL 37, LG-05 L6 review-only 12 | 약 6(±10). ±10 밖이면 문장 원문(수치 가림) 덧붙임 | REQ-LQMP (귀측이 close) |
| REQ-LQMP | review 분포 | — | `context_candidate_explanation`·`context_care_notice` 건수, '홀로 선 진료과 권고' FAIL 잔존 수(REQ-6NLZ 결정 3 자료) | REQ-LQMP·REQ-6NLZ |
| REQ-A2ZH | PHR 350 unmet 수 | UV-01 36 · UV-02 122 · UV-04 67 · PV-01 1(B0005) · PV-03 61 | 26건(21문항: B0005·B0036·B0052·B0132·B0136·B0153·B0325·B0446·B0502·B0527·B0588·B0715·B0744·B0824·B0833·B0925·B0934·B0978·B1029·B1291 외) 해소. 문장 원문 DOC-H6HQB 로 대조 | REQ-A2ZH (해소되면 호스트가 close) |
| REQ-A2ZH | 통과→미충족 역방향 | 0 이어야 함(medical-eval 골든 50건 main 대비 0) | 역방향이 있으면 문항·항목·문장 번호 회신 | REQ-A2ZH |
| REQ-A2ZH(#59) | PHR 350 PV-04 | unmet 28 · met 131 · na 186 (compare.md PV 표) | 범위 한정·값 조회 의도의 unmet 28건(CASE 07·20 꼴)이 na 로. B0052·B0715·B0925(「간 수치만」)는 PV-03(#58)+PV-04(#59)로 참고 등급 A 기대 — 3건 등급을 따로 적는다. met→na 가 섞이므로 PV-04 는 unmet 수가 아니라 unmet→na 건수·잔존 unmet 의 의도 분류로 본다 | REQ-A2ZH |
| REQ-XDIA | 일반 650 SV 키워드 경로 met | 55(SV-04 34·SV-02 27·SV-03 12), 골든 must-not-met 6건 | 불변(이 run 은 SV 를 바꾸지 않음) — cl-v3·sv-v4 전후 비교의 새 기준선이 된다 | REQ-XDIA (PR 뒤) |

- REQ-OOVZ(PHR 350 금지 표현 재검토, 10/26)와의 관계: 이 run 에서도 answer 블록(validity_answer)은 350/350 no_rubric 으로 나온다 — 호스트가 `rubric=` 을 넘기지 않기 때문(eval_v3.py:944, PHR 시나리오 rubric_json 빈 값). REQ-OOVZ 가 요구한 required_met·forbidden_hit 전후 집계는 이 run 으로 만들 수 없다. 연결 여부는 사람 결정(docs/eval_v3/phr350_rubric_review_req_oovz_20261026.md §2·§4).
- LG 축은 v323 과 '판정기 판 변경' 으로 표기하고 섞어 비교하지 않는다. UV·PV 축도 같다(미충족→충족만 생겨야 하므로 역방향 0 확인이 핵심).
- PV-04: 범위 한정 질문(「간 수치만」)의 추세 요구는 REQ-NIAR 「가」(10/26) 로 결정되어 PR #59(pv-v5)에 반영됐다 — 위 표의 #59 행. 더 이상 별도 결정 대기 없음.

## REQ-HMHK(10/26) — 참고 등급(grade_legacy) 표기와 판정 사유 노출, 호스트가 고칠 자리

현재 상태(origin/master 058f643 기준, 자동 처리에서 조사만 함 — 코드 변경·커밋 없음):
- 저장: `eval_v3.py` compact() 가 `validity_grade = grade or grade_legacy`, `validity_grade_source = "legacy"` 로 저장(246~258행). `validity_items[]`·`uv_items[]` 는 id·result·detail(+UV 는 quotes·sentence_idx) 저장. 연동 규격의 `diagnostics[]` 는 **저장하지 않음**(origin/master py·html 에 diagnostics 없음) — PV-03·04·05·12 는 v3.23 결과에서 validity_items 안에 들어 있어 detail 은 남는다.
- 최종 판정 열: `eval_v3.verdict_of()`(638행)·`history.html v3VerdictOf`(2300행)가 법률 pass 이면 **validity_grade(=grade_legacy) 글자를 최종 판정으로 보여 준다**(A~D, 없으면 PASS). PHR 350 에서 등급 B 가 「최종 판정 B」로 읽히는 길이 여기다.
- history.html 결과 카드(2445~2460행): 배지 [최종 판정 B][점수][게이트 통과][기록 활용 B][사용자 가치 A] → 걸린 규칙 chips → 미충족 항목 chips(id 만) → 「구문별 판정 근거」표(기준·판정·문장·걸린 구문·근거 = items[].detail, 2369~2418행). CSV 내보내기(1705행) 열 `validity_grade`·`uv_grade` 에 참고 표기 없음.
- grade_viewer.html 만 `PV B*` + 범례 「PV* = v3.0 방식 등급(grade_legacy)」(176·212행). scenario_manager 1586 「기록 활용 B」, external_eval 650·664·761·1132, share_eval 333·372 는 「PV 등급 B (ok)」 — 참고 표기 없음(external_eval·share_eval 은 미충족 id+detail 은 보임).
- 보고: `reports/v3_runs/compare_rejudge_v320.py` 119행 표 제목 「유효성(PV/SV) 등급」·「사용자 가치(UV) 등급」, 참고 표기 없음. 10/22 compare.md 에는 10/26 읽는 법 머리말을 덧붙였다. dashboard.py 는 등급을 쓰지 않음.

할 일(사람 세션 PR, 한 주제):
1. 등급 라벨을 「참고 등급 B(진단용)」로 바꾸고 최종 판정 배지는 PHR(grade=null, source=legacy)이면 **법률·evidence·answer 결과만**(예: PASS · 게이트 통과 · evidence pass · answer no_rubric) 으로 그린다 — `verdict_of`/`v3VerdictOf` 는 집계(run_summary·VERDICT_ORDER)에도 쓰이므로 표시용 함수를 따로 두거나 PHR 분기만 추가. 대상: history.html(2300·2445·1705), scenario_manager.html 1586, external_eval.html 650·664·761·1132, share_eval.html 333·372, grade_viewer.html 176·212, compare_rejudge_v320.py 119.
2. 미충족 항목마다 detail 을 RAG 팀이 보는 보고(compare.md D 등급 표·CSV·공유 화면)에 넣기 — 저장은 이미 있으므로 표시만. `diagnostics[]` 저장은 연동 규격(DOC-WFMDR v0.5.28)에서 items 와 분리된 뒤 compact() 에 추가.
3. CASE-23·62 PV-12 결과표: `reports/v3_runs/rj1000_v323_20261022/pv12_case23_62_20261026.md`(+추출 스크립트 2개). 18153a9 run 뒤 같은 스크립트로 덧붙인다.

## 사람 결정이 필요한 것
- ~~1~3 의 실행 시점(REQ-6NLZ 결정 2)~~ **끝남(10/26)** — 사용자 결정 (a), 18153a9 올림(host PR #69, master 9a3532a)·Job 재빌드·1000건 재판정 run 두 개 실행. 남은 결정은 REQ-6NLZ 결정 3(「홀로 선 진료과 권고」 FAIL 잔존 수 → compare.md (a) 절).
- REQ-HMHK 표시 변경 PR(위 절 할 일 1·2)의 실행 여부·시점 — 요청자(medical-eval)는 10/29 회신 기한. 권고: 서브모듈 18153a9 올림 PR 과 별도 PR 로 다음 사람 세션에서.
- 대기 중인 다른 결정과의 묶음: 정답지 A87·B63 반영(REQ-Z2Q7)·review-only 12건 fail/review(REQ-NBSW)는 이 run 과 독립 — 묶지 않아도 LG·UV·PV 비교에 영향 없음.
