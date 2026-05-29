# 데이터 수집 전략 — 목표와 비전 (post-MVP)

- 작성: 2026-05-30
- 범위: '나만의 주치의' Evidence-first Medical RAG의 **근거(Evidence) 데이터 수집 범위·목표·로드맵**
- 전제: GraphRAG 미사용, 한국 사용자 대상, 출처기반·진단/처방 금지 (작업지시서 정합)
- 관련: docs/eval_report_200.md(§5-f 근거 포화), 작업지시서 §3(소스 우선순위)·§11(평가지표)·§14(운영)

---

## 0. North Star (북극성)

> **"한국 사용자가 묻는 모든 흔한 증상·질환·약물·검사·예방접종 질문에 대해, 국내 공식 출처 기반의 최신·등급화·추적가능한 근거로 답할 수 있는 의료 근거 베이스."**

MVP("일부 증상에 어느 정도 근거 인용") → Vision("증상·약물·질환 공간을 체계적으로 커버하고, 모든 의학적 claim이 신선하고 검증된 출처로 뒷받침되며, 운영상 지속 갱신·거버넌스되는 근거 베이스").

성공의 단일 척도: **answerable-with-grounding rate** — "흔한 의료 질문 중 HIGH 근거로 답 가능한 비율"을 MVP의 낮은 수준 → 95%+로.

---

## 1. 현재 상태 (Baseline, 2026-05-30)

| 소스(kb_sources) | 성격 | 규모(약) | 우선순위 | 상태 |
|---|---|---|---|---|
| kdca_api / health_kdca | 질병관리청·국가건강정보포털 | ~1,074 청크 | 1 | **포화**(재수집 inserted=0) |
| consultation_seed | 자체 증상 교육콘텐츠 | ~440 | 2 | 안정 |
| nemc | 응급의료포털 | ~139 | 1 | 포화 |
| mfds_dur | 식약처 DUR | 8문서/52청크 | 1 | **부분**(8종×100=800건만) |
| consultation_checklist | 42증상 문진 가이드 | 42문서 | 2 | 신규 |
| guideline_internal | 내부 지침 | ~36 | 2 | 안정 |

**진단(eval_report §5-d/f)**: 검색 evidence_quality **insufficient 77%**, citation coverage **~0.54**(의학주장 46% 인용부족). 즉 **현재 근거량이 질의 공간을 못 덮는다**가 정량 확인됨. 공공 소스는 포화 → **breadth(새 출처) + depth(레코드 확대)** 양쪽 확장 필요.

---

## 2. 확장의 5개 차원 (단순 "더 많이"가 아님)

| 차원 | 정의 | MVP | Vision 목표 |
|---|---|---|---|
| **Breadth(폭)** | 출처 기관 수 | 4~5 (KDCA/MFDS/NEMC) | 6단 전 계층 (법령·학회·국제·DUR·Cochrane·PubMed) |
| **Depth(깊이)** | 출처별 레코드 커버리지 | DUR 800건, 증상 일부 | DUR 전 품목, 주요 질환·증상 전수 |
| **Freshness(신선도)** | 개정·갱신 추적 | 수동·1회성 | 출처별 갱신주기 SLA + superseded 처리 |
| **Structure(구조/품질)** | chunk_type·entity·evidence_level 태깅 | 부분 | 전 청크 등급·인구·위험 태깅 |
| **Governance(거버넌스)** | 라이선스·검수·감사 | source_registry 일부 | 라이선스 준수·정기검수·출처감사 완비 |

---

## 3. 소스 범위 로드맵 (작업지시서 §3.1 6단 정합)

| 우선 | 계층 | 대표 출처 | 현재 | 목표 단계 | 갱신주기 |
|---:|---|---|---|---|---|
| 1 | 국내 법령/공공 | 국가법령정보센터, KDCA, MFDS, **HIRA** | KDCA✓ MFDS부분 | **HIRA·국가법령 추가** | 법령 주1, DUR 일1 |
| 2 | 국내 진료지침/전문기관 | 대한의학회, 질환별 학회, NECA | guideline_internal 소량 | **주요 학회 지침 수집** | 월1 |
| 3 | 국제 공신력 | WHO, CDC, NICE, USPSTF | 없음 | **국내 공백 보완용 선별** | 분기 |
| 4 | 약물 라벨/허가 | MFDS 허가사항, DailyMed | DUR만 | **DUR 전품목 + 허가사항** | 일1 |
| 5 | 체계적 문헌고찰 | Cochrane, SR/MA | 없음 | **고빈도 주제 선별** | 분기 |
| 6 | PubMed/PMC OA | PubMed, PMC | 없음 | **보조근거(영문, KR우선 후순위)** | 주1 |

**원칙**: KR-first(P4), 약물=DUR/MFDS 우선(P5), 논문<지침(P6), 라이선스 확인 후 수집(공공누리/PMC OA).

---

## 4. 커버리지 목표 & 측정 (gap-driven)

"얼마나 모았나"가 아니라 **"질의 공간을 얼마나 덮나"**로 측정:

| KPI | 정의 | 현재 | Vision 목표 |
|---|---|---|---|
| Answerable-with-grounding | HIGH/MEDIUM 근거로 답 가능 질의 비율 | 낮음(insufficient 77%) | ≥90% |
| Citation coverage | 의학주장 중 인용 보유 비율 | ~0.54 | ≥0.95 (지시서 §11.1) |
| Symptom coverage | 42증상 + 주요 질환 근거 보유율 | 부분 | 핵심 증상·만성질환 전수 |
| Drug coverage | DUR/허가 약물 커버 | 일부 | 주요 처방 약물 전수 |
| Freshness lag | 출처 개정~반영 지연 | 미측정 | 출처별 SLA 내 |

**Gap 탐지 루프(운영 핵심)**: 배치 평가에서 evidence_quality=insufficient / citation coverage 낮은 질의 → **미충족 주제 자동 수집 큐**로 적재 → 우선순위대로 수집. (= 평가가 수집을 견인)

---

## 5. 단계별 계획 (post-MVP)

**Phase 2 — 약물·국내 권위 심화 (즉시~단기)**
- DUR 레코드 확대(800→수천), HIRA DUR 연동, MFDS 허가사항.
- 국가법령(의료법·개인정보법) 수집 → 법적 경계 grounding.
- 목표: drug coverage·법률 grounding 확보, citation coverage 0.54→0.7+.

**Phase 3 — 진료지침·증상/질환 전수 (중기)**
- 주요 학회 지침, 질환별 patient-info 전수, 증상-질환 매핑 보강.
- Gap 탐지 루프 가동(평가→수집 자동화).
- 목표: symptom/disease coverage·answerable rate 90%+.

**Phase 4 — 국제 보완·문헌·거버넌스 완성 (장기)**
- WHO/CDC/NICE 선별, Cochrane/SR, PubMed/PMC 보조.
- 출처 갱신 스케줄러·superseded 처리·라이선스/검수 콘솔 운영화.
- 목표: 최신성 SLA·거버넌스 완비, 운영 안정.

---

## 6. 거버넌스 & 운영 (지속가능성)

- **Source Registry 규율**: 모든 출처 priority_rank·jurisdiction·license_type·update_cycle·last_checked_at 관리(스키마 존재, migration 009).
- **갱신 스케줄러**: 출처별 주기(법령 주1 / DUR·KDCA 일1 / 학회 월1 / 논문 주1, 지시서 §14.1).
- **Superseding**: 개정 시 구문서 is_active=false·superseded_by 처리(오래된 근거 인용 방지, P5/E5).
- **라이선스**: 공공누리 유형·PMC OA 재사용 조건 확인 후 저장. PubMed는 abstract/메타 중심.
- **품질 게이트**: 수집 시 compliance 필터(현재 violation 스킵 동작 중) + chunk_type/evidence_level 태깅.
- **감사**: answer_id↔evidence_ids 추적(이미 evidence_pack_json 감사), 출처 접근 로그.

---

## 7. 제약·리스크

- **규제 경계**: 생성형 AI 의료기기 해당성(식약처 가이드라인) — 근거 확대가 "진단 보조"로 해석되지 않도록 일반정보 범위 유지.
- **라이선스**: 비공개/저작권 출처 무단수집 금지. 공공누리·OA만.
- **비용**: 수집·임베딩·저장 비용 — Phase별 ROI(질의 커버리지 기여) 기준 우선순위.
- **중복·신선도**: dedup(현재 동작) + superseded 없으면 오래된/중복 근거 누적.
- **국제 출처 jurisdiction 충돌**: KR-first 정책으로 reranker/Evidence Pack에서 해외 후순위(이미 conflict_resolver 존재).

---

## 8. 즉시 실행 후보 (이 비전의 Phase 2 착수점)

1. **DUR 레코드 확대** (기존 dur_collector+키, rows↑) — 최저비용·최고가치, 약물근거 즉시 확대.
2. **HIRA DUR 수집기**(data.go.kr 15127983) 신규.
3. **Gap 탐지 루프** 1차 — 배치 평가의 insufficient 질의를 수집 우선순위로 환류.

→ 본 문서 승인 후, Phase 2 착수 항목(1~3)부터 티켓화하여 진행.
