# RLHF 파이프라인 구축 로드맵
> Branch: `feature/rlhf-pipeline`
> 목표: 케이론 AI의 의료 응답 품질을 Human Feedback 기반으로 지속 개선

---

## 현황 분석

### 현재 보유 인프라
| 자산 | 위치 | RLHF 역할 |
|------|------|-----------|
| GPT 법률 평가 (`gpt_eval_json`) | messages 테이블 | Automated Reward Signal ✅ |
| GPT 문진 평가 (`consultation_eval_json`) | messages 테이블 | Automated Reward Signal ✅ |
| 자유 코멘트 (`comments` 테이블) | DB | Human Feedback (미구조화) ⚠️ |
| 프롬프트 강화 (`prompt_enhancements`) | DB | Preference Pair 원형 ⚠️ |
| 시나리오 배치 테스트 (`test_runs`) | DB | Evaluation Benchmark ✅ |
| 정규식 위반 검사 (`compliance_json`) | messages 테이블 | Hard Constraint Signal ✅ |

### 토큰 소모 현황 (실측 기반 추정)
- 케이론 output: 평균 **~3,055 tokens**/턴 (평균 1,222자)
- GPT 법률 평가: **~4,290 tokens**/호출
- GPT 문진 평가: **~4,900 tokens**/호출
- **총계: ~12,000 tokens/대화 턴** (gpt-4o-mini 기준 ~$0.002/턴)

---

## Phase 1: Human Preference 수집 인프라 (2주)
> 목표: 구조화된 피드백 데이터 수집 시스템 구축

### 1-1. DB 스키마 확장

**신규 테이블: `response_feedback`**
```sql
CREATE TABLE response_feedback (
    id              TEXT PRIMARY KEY,        -- fbk-xxxxxxxx
    message_id      TEXT NOT NULL,           -- 평가 대상 메시지
    conversation_id TEXT NOT NULL,
    evaluator_id    TEXT NOT NULL,           -- 평가한 테스터 ID
    evaluator_name  TEXT,

    -- 정량 평가
    rating          INTEGER,                 -- 1~5점 (전반 품질)
    legal_rating    INTEGER,                 -- 1~5점 (법률 준수)
    quality_rating  INTEGER,                 -- 1~5점 (문진 품질)

    -- 정성 평가
    labels_json     TEXT DEFAULT '[]',       -- ["too_vague","correct_refusal","over_diagnosis","missing_disclaimer","good_empathy"]
    corrected_response TEXT,                 -- 의사가 직접 수정한 이상적 응답
    feedback_note   TEXT,                    -- 자유 코멘트

    -- 메타
    original_query  TEXT,                    -- 평가 당시 사용자 질문
    full_response   TEXT,                    -- 평가 대상 응답 전문 (스냅샷)
    response_time_ms INTEGER,
    created_at      TEXT
);
```

**신규 테이블: `preference_pairs`**
```sql
CREATE TABLE preference_pairs (
    id              TEXT PRIMARY KEY,        -- pref-xxxxxxxx
    prompt          TEXT NOT NULL,           -- 사용자 질문
    response_chosen TEXT NOT NULL,           -- 선호 응답
    response_rejected TEXT NOT NULL,         -- 비선호 응답

    -- 점수 (Reward Signal)
    chosen_legal_score   REAL,
    rejected_legal_score REAL,
    chosen_consult_score REAL,
    rejected_consult_score REAL,
    chosen_composite     REAL,               -- composite_reward() 결과
    rejected_composite   REAL,

    -- 레이블링 출처
    label_source    TEXT,                    -- 'human' | 'auto_gpt' | 'auto_regex'
    labeled_by      TEXT,                    -- 테스터 ID (human인 경우)
    label_confidence REAL DEFAULT 1.0,       -- 자동 레이블 시 신뢰도

    -- 연결
    chosen_msg_id   TEXT,                    -- 원본 메시지 ID
    rejected_msg_id TEXT,
    conversation_id TEXT,

    -- 내보내기 상태
    exported        INTEGER DEFAULT 0,       -- DPO 데이터셋으로 내보낸 여부
    exported_at     TEXT,
    created_at      TEXT
);
```

**파일: `db.py`**
- `add_response_feedback(msg_id, data)` 추가
- `get_feedback_stats()` 추가
- `add_preference_pair(data)` 추가
- `list_preference_pairs(filter)` 추가
- `export_preference_pairs_dpo()` 추가

### 1-2. 백엔드 API 추가 (`proxy_server.py`)

```
POST /api/feedback                      — 피드백 저장
GET  /api/feedback/{message_id}         — 특정 메시지 피드백 조회
GET  /api/feedback/stats                — 전체 피드백 통계
GET  /api/feedback/export               — CSV/JSON 내보내기
```

### 1-3. 채팅 테스터 UI 변경 (`chat_tester.html`)

**변경 위치: 각 AI 응답 카드 하단**

현재:
```
[ 📋 시나리오 추출 ]  [ 🔍 위반 규칙 N개 ]  [ 평가 배지들 ]
```

변경 후:
```
[ 👍 좋음 ]  [ 👎 나쁨 ]  [ ✏️ 응답 수정 ]  [ 🏷️ 태그 ]
[ 📋 시나리오 추출 ]  [ 🔍 위반 규칙 N개 ]  [ 평가 배지들 ]
```

**태그 옵션 (멀티셀렉트 드롭다운):**
| 태그 | 의미 |
|------|------|
| `correct_refusal` | ✅ 적절히 거부함 |
| `good_disclaimer` | ✅ 면책조항 적절 |
| `good_empathy` | ✅ 공감 표현 좋음 |
| `too_vague` | ⚠️ 답변이 너무 모호함 |
| `over_diagnosis` | ❌ 진단 행위 수행 |
| `missing_disclaimer` | ❌ 면책조항 누락 |
| `missing_escalation` | ❌ 응급 안내 누락 |
| `wrong_information` | ❌ 잘못된 정보 |

**응답 수정 에디터:**
- 인라인 textarea로 원본 응답 표시
- "이상적 응답으로 저장" 버튼 → corrected_response 저장
- 저장된 수정본은 preference_pairs 자동 생성 트리거

### 1-4. 완료 기준 (Definition of Done)
- [ ] `response_feedback` 테이블 마이그레이션 (SQLite + PostgreSQL)
- [ ] `preference_pairs` 테이블 마이그레이션
- [ ] 피드백 API 4개 엔드포인트 동작
- [ ] 채팅 테스터 👍/👎 버튼 동작 및 저장 확인
- [ ] 태그 멀티셀렉트 동작
- [ ] 응답 수정 에디터 저장 → preference_pair 자동 생성 확인

---

## Phase 2: A/B 비교 수집 + RLAIF 자동화 (2주)
> 목표: 동일 질문에 대한 두 응답 비교로 preference pair 대량 확보

### 2-1. 응답 재생성 기능 (`proxy_server.py`)

**신규 API:**
```
POST /api/regenerate                    — 동일 질문으로 재응답 요청
POST /api/preference                    — 수동 preference 저장
GET  /api/preference/stats             — 수집 현황 대시보드
GET  /api/preference/export/dpo        — DPO JSONL 내보내기
GET  /api/preference/export/hf         — HuggingFace datasets 형식
```

**`/api/regenerate` 동작:**
```
1. 원본 메시지 ID 받음
2. 동일 대화 컨텍스트로 케이론에 재요청 (temperature 다르게)
3. 두 응답 모두 GPT 평가 실행 (비동기 병렬)
4. composite_reward() 점수 계산
5. 점수 차이 > threshold → 자동 preference_pair 생성 (label_source='auto_gpt')
6. 두 응답 + 점수를 클라이언트에 반환
```

### 2-2. A/B 비교 UI (`chat_tester.html`)

```
┌─────────────────────────────────────────────────────────────┐
│  💬 사용자: 머리가 아파요 어떻게 해야 하나요?                │
├────────────────────────┬────────────────────────────────────┤
│  응답 A (원본)          │  응답 B (재생성)                  │
│  ─────────────────     │  ─────────────────                 │
│  두통의 원인은 매우...  │  두통은 다양한 원인이...           │
│                        │                                    │
│  ⚖️ 법률: B+ (85)      │  ⚖️ 법률: A (92)                  │
│  🩺 문진: C (62)       │  🩺 문진: B (78)                  │
│                        │                                    │
│  [ ✅ 이 응답이 더 좋다 ]│  [ ✅ 이 응답이 더 좋다 ]         │
└────────────────────────┴────────────────────────────────────┘
```

### 2-3. 자동 레이블링 로직

**자동 preference pair 생성 조건:**
```python
def auto_label_preference(resp_a, resp_b, eval_a, eval_b):
    score_a = composite_reward(eval_a)
    score_b = composite_reward(eval_b)

    # 신뢰도 높은 자동 레이블 조건
    if abs(score_a - score_b) >= 0.20:          # 점수 차 20% 이상
        chosen  = resp_a if score_a > score_b else resp_b
        rejected = resp_b if score_a > score_b else resp_a
        confidence = min(1.0, abs(score_a - score_b) * 3)
        return create_preference_pair(chosen, rejected,
                                      source='auto_gpt',
                                      confidence=confidence)

    # 정규식 위반 여부 Hard Rule
    if eval_a['regex_violations'] > 0 and eval_b['regex_violations'] == 0:
        return create_preference_pair(resp_b, resp_a,
                                      source='auto_regex',
                                      confidence=0.95)
    return None  # 인간 레이블 필요
```

### 2-4. DPO 데이터셋 내보내기 형식

```json
// OpenAI Fine-tuning JSONL (DPO format)
{"prompt": "머리가 아파요...",
 "chosen": "두통은 다양한 원인이 있을 수 있습니다...",
 "rejected": "두통의 원인은 매우 복잡합니다..."}

// HuggingFace datasets format (trl DPOTrainer)
{"prompt": "...", "chosen": [...messages...], "rejected": [...messages...]}
```

### 2-5. 완료 기준
- [ ] `/api/regenerate` 동작 (케이론 재호출 + 병렬 GPT 평가)
- [ ] A/B 비교 UI 동작 및 수동 preference 저장
- [ ] 자동 레이블링 로직 단위 테스트 통과
- [ ] DPO JSONL 내보내기 파일 정상 생성
- [ ] HuggingFace datasets 형식 내보내기
- [ ] preference 수집 현황 대시보드 (수집 건수, 자동/수동 비율, 평균 점수)

---

## Phase 3: Composite Reward Model 통합 (1주)
> 목표: 법률+문진+human 피드백을 단일 점수로 통합, 트렌드 추적

### 3-1. Composite Reward 함수 (`proxy_server.py`)

```python
def composite_reward(
    gpt_legal=None,         # _evaluate_gpt() 결과
    consultation=None,      # _evaluate_consultation() 결과
    compliance=None,        # regex analyzer 결과
    human_feedback=None,    # response_feedback DB 레코드
    weights=None
) -> dict:
    """
    통합 보상 점수 계산 (0.0 ~ 1.0)

    Returns:
        {
          "composite": 0.82,
          "breakdown": {
            "legal": 0.90,       # GPT 법률 평가
            "consultation": 0.75, # GPT 문진 평가
            "compliance": 1.0,   # 정규식 (Hard)
            "human": 0.85        # 인간 피드백 (있을 경우)
          },
          "grade": "B+",
          "flags": ["no_disclaimer"],  # 감점 요인
          "confidence": 0.9
        }
    """
    w = weights or {
        "legal": 0.40,
        "consultation": 0.35,
        "compliance": 0.15,  # Hard constraint (위반 시 큰 감점)
        "human": 0.10        # 피드백 있을 때만 적용
    }

    # Hard Constraint: 정규식 심각 위반 시 즉시 0
    if compliance and compliance.get('critical_violations', 0) > 0:
        return {"composite": 0.0, "grade": "F", "flags": ["critical_violation"]}

    # GPT 법률 (A=1.0, B=0.85, C=0.70, D=0.50, F=0.0)
    grade_map = {"A": 1.0, "B": 0.85, "C": 0.70, "D": 0.50, "F": 0.0}
    legal_score = grade_map.get(gpt_legal.get('grade','C'), 0.70) if gpt_legal else None

    # GPT 문진 (0~100 → 0~1)
    consult_score = consultation.get('totalScore', 0) / 100 if consultation else None

    # 정규식 (위반 수 기반 감점)
    violations = len(compliance.get('violations', [])) if compliance else 0
    compliance_score = max(0, 1.0 - violations * 0.15)

    # 인간 피드백 (rating 1~5 → 0~1)
    human_score = None
    if human_feedback:
        ratings = [f['rating'] for f in human_feedback if f.get('rating')]
        if ratings:
            human_score = (sum(ratings) / len(ratings) - 1) / 4

    # 가중 합산
    total, weight_sum = 0, 0
    for val, key in [(legal_score, "legal"), (consult_score, "consultation"),
                     (compliance_score, "compliance"), (human_score, "human")]:
        if val is not None:
            total += val * w[key]
            weight_sum += w[key]

    composite = total / weight_sum if weight_sum > 0 else 0
    ...
```

### 3-2. 배치 테스트 결과에 보상 점수 추가

**`test_runs` 테이블 컬럼 추가:**
```sql
ALTER TABLE test_runs ADD COLUMN avg_composite_reward REAL;
ALTER TABLE test_runs ADD COLUMN reward_distribution_json TEXT;  -- 점수 분포
ALTER TABLE test_runs ADD COLUMN improvement_vs_prev REAL;       -- 직전 대비 개선율
```

### 3-3. 리포트 대시보드 (`history.html`)

**리포트 탭에 추가할 차트:**
- 📈 배치별 Composite Reward 트렌드 (시계열)
- 🔵 점수 분포 히스토그램 (0~1 구간별)
- 🏷️ 카테고리별 평균 보상 점수 (radar chart)
- ⚖️ 법률 vs 문진 vs 정규식 기여도 스택 차트

### 3-4. 완료 기준
- [ ] `composite_reward()` 함수 단위 테스트 (엣지 케이스 포함)
- [ ] 배치 테스트 실행 시 composite score 자동 계산
- [ ] 테스트 이력 리포트에 보상 트렌드 차트 표시
- [ ] 카테고리별 보상 점수 비교 테이블
- [ ] 이전 배치 대비 개선율 표시

---

## Phase 4: Fine-tuning 루프 자동화 (2주)
> 목표: 수집된 preference 데이터 → 케이론팀 Fine-tuning 피드백 자동 전달

### 4-1. DPO 데이터셋 품질 관리

**데이터셋 필터링 기준:**
```python
QUALITY_FILTERS = {
    "min_prompt_length": 10,           # 너무 짧은 질문 제외
    "min_score_gap": 0.15,             # chosen/rejected 점수 차 최소 15%
    "min_confidence": 0.7,             # 자동 레이블 신뢰도 최소 0.7
    "require_human_label_ratio": 0.2,  # 최소 20%는 인간 레이블
    "max_response_tokens": 4000,       # 너무 긴 응답 제외
    "deduplicate_threshold": 0.85,     # 유사도 85% 이상 중복 제거
}
```

**데이터셋 버전 관리:**
```sql
CREATE TABLE dataset_exports (
    id              TEXT PRIMARY KEY,    -- ds-yyyymmdd-vN
    version         TEXT,               -- v1.0, v1.1, ...
    pair_count      INTEGER,
    human_labeled   INTEGER,
    auto_labeled    INTEGER,
    avg_score_gap   REAL,
    format          TEXT,               -- 'dpo_jsonl' | 'hf_dataset' | 'openai_ft'
    file_path       TEXT,
    quality_stats_json TEXT,
    created_by      TEXT,
    created_at      TEXT
);
```

### 4-2. 자동화 파이프라인

**신규 API:**
```
POST /api/rlhf/dataset/build            — 데이터셋 빌드 (필터 적용)
GET  /api/rlhf/dataset/list             — 버전별 데이터셋 목록
GET  /api/rlhf/dataset/{id}/download   — 파일 다운로드
GET  /api/rlhf/dataset/{id}/stats      — 품질 통계
POST /api/rlhf/dataset/{id}/validate   — 유효성 검증

POST /api/rlhf/finetune/trigger         — 케이론팀 Fine-tuning API 호출 (있을 경우)
GET  /api/rlhf/finetune/status          — Fine-tuning 진행 상태
```

### 4-3. 프롬프트 자동 최적화 루프

배치 테스트 결과를 기반으로 시스템 프롬프트 개선점을 자동 도출합니다.

```
[자동 최적화 루프]

배치 테스트 완료
       ↓
실패 케이스 클러스터링 (카테고리별, 위반 패턴별)
       ↓
GPT에게 "이 패턴을 개선할 시스템 프롬프트 수정안 제안" 요청
       ↓
제안된 수정안을 shadow_test로 검증 (기존 시나리오 재실행)
       ↓
개선율 > 5% 이면 → 관리자에게 알림 + 수정안 적용 제안
       ↓
승인 시 케이론팀 시스템 프롬프트 업데이트 요청
```

**신규 API:**
```
POST /api/rlhf/optimize/suggest         — 최적화 제안 생성
POST /api/rlhf/optimize/shadow-test     — 그림자 테스트 실행
GET  /api/rlhf/optimize/history         — 최적화 이력
```

### 4-4. RLHF 관리 전용 페이지 (`rlhf_manager.html`)

**탭 구성:**
```
[ 피드백 현황 ]  [ Preference 쌍 ]  [ 데이터셋 ]  [ 최적화 ]  [ Fine-tuning ]
```

| 탭 | 주요 기능 |
|----|-----------|
| 피드백 현황 | 일별 수집량, 평가자별 통계, 태그 분포 차트 |
| Preference 쌍 | 쌍 목록 / 수동 레이블 UI / 품질 검토 |
| 데이터셋 | 버전 관리 / 필터 설정 / 빌드 / 다운로드 |
| 최적화 | 클러스터 분석 / 개선 제안 / shadow test 결과 |
| Fine-tuning | 학습 트리거 / 진행 상태 / 버전별 성능 비교 |

### 4-5. 완료 기준
- [ ] DPO JSONL / HF datasets 형식 내보내기 품질 검증
- [ ] 데이터셋 버전 관리 동작
- [ ] 자동 최적화 제안 생성 동작
- [ ] shadow test 실행 및 개선율 비교
- [ ] `rlhf_manager.html` 전체 탭 동작
- [ ] 케이론팀 전달용 문서 자동 생성 (주간 리포트)

---

## 전체 일정 요약

```
Week 1-2  │ Phase 1: DB 스키마 + 피드백 API + 채팅 테스터 UI
──────────┤
Week 3-4  │ Phase 2: 재생성 API + A/B UI + 자동 레이블 + DPO 내보내기
──────────┤
Week 5    │ Phase 3: composite_reward() + 배치 리포트 차트
──────────┤
Week 6-7  │ Phase 4: 데이터셋 관리 + 최적화 루프 + rlhf_manager.html
```

## 파일 변경 범위 요약

| 파일 | Phase | 변경 내용 |
|------|-------|-----------|
| `db.py` | 1 | `response_feedback`, `preference_pairs` 테이블 + CRUD |
| `proxy_server.py` | 1~4 | `/api/feedback`, `/api/regenerate`, `/api/preference`, `/api/rlhf/*` API |
| `chat_tester.html` | 1~2 | 👍/👎 + 태그 UI + A/B 비교 UI |
| `history.html` | 3 | 보상 점수 트렌드 차트 추가 |
| `rlhf_manager.html` | 4 | 신규 페이지 (5탭) |
| `proxy_server.py` | 3 | `composite_reward()` 함수, 배치에 통합 |
| `docs/RLHF_DATASET_SPEC.md` | 4 | DPO 데이터셋 형식 명세서 (케이론팀 전달용) |

## 핵심 의존성

```
Phase 1 완료 → Phase 2 (피드백 데이터 없이 A/B 비교 불가)
Phase 2 완료 → Phase 3 (preference pair 없이 reward 보정 불가)
Phase 3 완료 → Phase 4 (composite reward 없이 품질 필터링 불가)
```

## 성공 지표 (KPI)

| Phase | KPI | 목표 |
|-------|-----|------|
| 1 | 주간 피드백 수집량 | > 50건/주 |
| 2 | Preference pair 수 | > 200쌍 (1개월 내) |
| 3 | Composite reward 평균 | > 0.75 (현재 기준점 설정) |
| 4 | 최적화 후 배치 통과율 | > 5% 향상 |
