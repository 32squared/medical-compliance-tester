"""
심정지/발열 보강용 단문 FAQ KB.
직접 작성 콘텐츠 (GPT 미사용 — 위반 패턴 완전 제어).
status='active' 직접 적재.
"""

import io
import os
import sys
import logging

# 한글 출력 보장
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 프로젝트 루트를 sys.path에 추가
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("seed_faq")

# 직접 작성 FAQ — 의료법 27조 준수, 명령형 금지, 권유형/안내형만
FAQS = [
    # ─────────── 심정지 (5개 변형) ───────────
    {
        "title": "성인 심정지 시 어떻게 해야 하나요?",
        "evidence_topic": "cardiac_arrest",
        "symptom_tags": ["심정지", "CPR", "흉부압박"],
        "content": """## 즉시 행동
- 어깨를 두드려 의식을 확인합니다.
- 의식과 호흡이 없으면 119에 신고합니다.
- 주변 사람에게 자동심장충격기(AED)를 요청합니다.
- 흉부 가운데(가슴뼈 아래쪽 절반)에 손을 겹쳐 압박합니다.
- 압박 속도는 분당 100~120회, 깊이는 5~6cm입니다.
- 30회 압박 후 인공호흡 2회를 시행합니다.
- 119 도착 또는 환자가 반응할 때까지 반복합니다.

## 의심 원인
- 심근경색, 부정맥, 익수, 약물 과다, 외상 등이 흔한 원인입니다.

## 상세 설명
- 심정지는 심장이 갑자기 멈춰 혈액 순환이 중단된 상태입니다.
- 즉각적인 심폐소생술이 생존율을 크게 높입니다.
- AED는 심실세동을 전기 충격으로 정상화하는 장치입니다.

## 추가 확인 사항
- AED가 도착하면 즉시 패드를 부착합니다.
- "제세동 권고" 음성이 나오면 모두 환자에게서 떨어진 상태에서 버튼을 누릅니다.
- 제세동 후 즉시 흉부압박을 다시 시작합니다.""",
    },
    {
        "title": "성인 심정지 응급처치 순서",
        "evidence_topic": "cardiac_arrest",
        "symptom_tags": ["심정지", "응급처치", "119"],
        "content": """## 즉시 행동
1. 의식 확인 — 어깨를 두드리며 큰 소리로 부릅니다.
2. 119 신고 — "심정지로 의심된다"고 명확히 알립니다.
3. AED 요청 — 주변에 자동심장충격기를 가져오게 합니다.
4. 흉부압박 시작 — 분당 100~120회, 깊이 5~6cm.
5. 30:2 비율 — 흉부압박 30회 후 인공호흡 2회.

## 의심 원인
- 심실세동이 가장 흔한 원인입니다.
- 심근경색, 익수, 외상, 약물 과다도 심정지를 유발합니다.

## 상세 설명
- 4~6분 이상 뇌 혈류가 차단되면 비가역적 손상이 발생합니다.
- 빠른 심폐소생술과 AED 사용이 생존율을 높이는 핵심입니다.

## 추가 확인 사항
- 의식·호흡 정상이면 옆으로 눕혀 기도를 확보합니다.
- 의료진 도착 전까지 압박을 멈추지 않는 것이 중요합니다.""",
    },
    {
        "title": "심폐소생술(CPR) 표준 절차",
        "evidence_topic": "cardiac_arrest",
        "symptom_tags": ["심폐소생술", "CPR", "흉부압박"],
        "content": """## 즉시 행동
- 환자를 단단한 바닥에 눕힙니다.
- 가슴뼈 아래쪽 절반에 한 손을 놓고 다른 손을 위에 겹칩니다.
- 팔꿈치를 펴고 어깨가 손 위에 오도록 자세를 잡습니다.
- 분당 100~120회 속도로 5~6cm 깊이 압박을 시행합니다.
- 압박과 이완 비율은 1:1, 압박 후 가슴이 완전히 올라오도록 합니다.

## 의심 원인
- 심정지의 흔한 원인: 심실세동, 심근경색, 무수축, 무맥성 전기활동.

## 상세 설명
- 가슴 압박은 혈액 순환을 인위적으로 유지하는 역할을 합니다.
- 압박 중단 시간을 최소화할수록 생존율이 높아집니다.

## 추가 확인 사항
- 1인 구조자: 30회 압박 + 2회 호흡.
- 2인 구조자: 1인이 압박, 1인이 인공호흡 교대.
- 2분마다 압박자 교대를 권장합니다.""",
    },
    {
        "title": "심장이 멈춘 사람 발견 시 행동",
        "evidence_topic": "cardiac_arrest",
        "symptom_tags": ["심정지", "의식없음", "119"],
        "content": """## 즉시 행동
- 의식 없음·호흡 없음이 확인되면 심정지로 간주합니다.
- 119 신고 후 즉시 흉부압박을 시작합니다.
- 흉부압박은 절대 중단하지 않습니다.

## 의심 원인
- 갑작스러운 심정지는 심실세동이 가장 흔합니다.
- AED가 가장 효과적인 초기 처치입니다.

## 상세 설명
- 목동맥 맥박 확인은 10초 이내에 시행합니다.
- 불확실하면 즉시 흉부압박을 시작하는 것이 권장됩니다.

## 추가 확인 사항
- AED 사용 가능 시 1분 이내 사용이 생존율을 크게 높입니다.
- 119 도착 시 응급 의료진에게 처치 경과를 전달합니다.""",
    },
    {
        "title": "심정지 환자에게 무엇을 해야 하나요?",
        "evidence_topic": "cardiac_arrest",
        "symptom_tags": ["심정지", "응급", "구조"],
        "content": """## 즉시 행동
- 안전한 장소로 옮기지 않고 그 자리에서 처치합니다.
- 119에 즉시 신고합니다.
- 흉부압박을 시작합니다 (분당 100~120회).
- AED가 있으면 즉시 부착합니다.

## 의심 원인
- 심정지의 주요 원인: 심근경색, 심부전, 부정맥, 익수, 외상.

## 상세 설명
- 심정지 발생 후 1분마다 생존율이 약 10% 감소합니다.
- 목격자 심폐소생술은 생존율을 2~3배 높이는 것으로 알려져 있습니다.

## 추가 확인 사항
- 인공호흡이 어려우면 흉부압박만 지속해도 효과가 있습니다.
- 손이 피로하면 30초마다 교대하는 것이 권장됩니다.
- 환자가 반응하거나 119가 도착할 때까지 멈추지 않습니다.""",
    },

    # ─────────── 발열 (5개 변형) ───────────
    {
        "title": "발열 시 어떻게 해야 하나요?",
        "evidence_topic": "fever",
        "symptom_tags": ["발열", "고열", "체온"],
        "content": """## 즉시 행동
- 체온계로 정확한 체온을 측정합니다.
- 충분한 수분을 섭취합니다.
- 가벼운 옷차림과 시원한 환경을 유지합니다.
- 미온수로 몸을 닦으면 열을 내리는 데 도움이 됩니다.
- 38.5도 이상 지속되거나 증상이 심하면 의료기관에 상담합니다.

## 의심 원인
- 감염(바이러스·세균), 염증, 열사병, 약물 반응 등 다양합니다.

## 상세 설명
- 발열은 체온이 37.5도 이상으로 상승한 상태입니다.
- 발열 자체는 감염에 대한 인체의 방어 반응입니다.
- 원인 파악을 위해 동반 증상 확인이 중요합니다.

## 추가 확인 사항
- 의식 변화, 목 강직, 발진, 호흡곤란이 있으면 응급실 방문이 권장됩니다.
- 39도 이상 고열이 3일 이상 지속되면 의사 진료가 필요합니다.
- 영유아·고령자·만성질환자는 더 빠른 진료가 권장됩니다.""",
    },
    {
        "title": "성인 열이 날 때 응급실에 가야 하나요?",
        "evidence_topic": "fever",
        "symptom_tags": ["발열", "응급실", "고열"],
        "content": """## 즉시 행동
- 체온이 38도 이상이면 충분한 휴식과 수분을 우선 합니다.
- 39도 이상 고열이거나 아래 증상이 있으면 응급실 방문이 권장됩니다.

## 의심 원인
- 다음 신호가 있으면 빠른 진료가 필요합니다:
  - 의식 저하 또는 혼란
  - 목이 뻣뻣함 (뇌수막염 가능성)
  - 호흡 곤란 또는 청색증
  - 점상 출혈성 발진
  - 3일 이상 지속되는 38.5도 이상 고열

## 상세 설명
- 뇌수막염 의심 시 즉각적인 응급 처치가 필요합니다.
- 패혈증은 고열과 함께 저혈압·빠른 맥박·의식 변화가 동반됩니다.

## 추가 확인 사항
- 동반 증상(복통·흉통·심한 두통)이 있으면 응급실 진료가 권장됩니다.
- 가까운 응급실 위치는 119에 문의할 수 있습니다.""",
    },
    {
        "title": "체온이 38도 넘을 때 대처법",
        "evidence_topic": "fever",
        "symptom_tags": ["발열", "해열", "미온수"],
        "content": """## 즉시 행동
- 체온을 정확히 측정합니다 (구강·고막·이마).
- 미지근한 물수건으로 이마·겨드랑이·사타구니를 닦습니다.
- 시원한 보리차·이온음료 등으로 수분을 보충합니다.
- 두꺼운 이불이나 옷을 벗고 통풍이 잘 되게 합니다.

## 의심 원인
- 바이러스 감염(감기·독감)이 성인 발열의 가장 흔한 원인입니다.
- 세균 감염, 요로감염, 폐렴도 고열을 유발할 수 있습니다.

## 상세 설명
- 미온수 마사지(약 30도 물수건)는 열 발산에 도움이 됩니다.
- 너무 차가운 물은 오히려 혈관을 수축시킬 수 있어 권장하지 않습니다.

## 추가 확인 사항
- 해열제 복용을 고려한다면 약사 또는 의사 상담 후 사용이 권장됩니다.
- 자가 처치 후 6시간 내 호전이 없으면 의료기관 상담이 권장됩니다.
- 의식 변화·심한 두통·발진이 동반되면 즉시 의료기관을 방문합니다.""",
    },
    {
        "title": "열이 나는데 어떻게 처치하나요?",
        "evidence_topic": "fever",
        "symptom_tags": ["발열", "처치", "해열"],
        "content": """## 즉시 행동
- 휴식을 충분히 취하고 수분을 자주 섭취합니다.
- 시원한 옷차림을 유지하고 실내 온도를 적절히 조절합니다.
- 미온수 마사지(약 30도 정도의 물수건)가 도움이 될 수 있습니다.

## 의심 원인
- 감기·독감 같은 바이러스 감염이 가장 흔합니다.
- 폐렴·요로감염·인후염 등 세균 감염도 가능합니다.
- 약물 반응·자가면역질환도 원인이 될 수 있습니다.

## 상세 설명
- 발열 시 하루 1.5~2L 이상의 수분 섭취가 권장됩니다.
- 고열이 지속되면 탈수와 전해질 불균형이 발생할 수 있습니다.

## 추가 확인 사항
- 3일 이상 지속, 39도 이상 고열, 동반 증상 악화 시 의사 진료가 권장됩니다.
- 영유아 38도 이상 발열은 즉시 의료기관 상담이 권장됩니다.""",
    },
    {
        "title": "성인 발열 단계별 대응",
        "evidence_topic": "fever",
        "symptom_tags": ["발열", "단계", "대응"],
        "content": """## 즉시 행동
- 37.5~38도 (미열): 수분 섭취, 휴식, 가벼운 옷차림.
- 38~38.5도: 미온수 마사지, 시원한 환경, 충분한 수분.
- 38.5~39도: 해열제 복용 고려(약사/의사 상담), 의료기관 진료 권장.
- 39도 이상: 의료기관 진료가 권장됩니다.
- 40도 이상: 응급실 방문이 권장됩니다.

## 의심 원인
- 미열(37.5~38도): 피로, 스트레스, 경미한 감염.
- 중등도 열(38~39도): 바이러스·세균 감염이 흔합니다.
- 고열(39도 이상): 세균 감염, 열사병, 중증 염증 가능성.

## 상세 설명
- 체온 측정 방법별 정상 범위: 구강 36.5~37.5도, 고막 36.5~37.5도, 이마 36~37도.
- 체온이 높을수록 기저 원인의 중증도가 높을 수 있습니다.

## 추가 확인 사항
- 의식 저하·경련·심한 두통·구토가 동반되면 즉시 응급실에 갑니다.
- 영유아·임산부·고령자·만성질환자는 더 낮은 체온에서도 의료기관 상담이 권장됩니다.""",
    },
]


def main():
    from kb_ingest import ingest_document, seed_kb_sources
    from collect_public_kb import precheck_violations

    # consultation_seed source 보장
    seed_kb_sources(sources=[{
        "id": "consultation_seed",
        "name": "자체 제작 증상 문진 체크리스트 (의사 자문 반영)",
        "source_type": "internal",
        "license": "proprietary",
        "update_frequency": "on_demand",
        "is_active": 1,
    }])

    success = 0
    failed = 0
    skipped = 0

    for faq in FAQS:
        try:
            # 위반 사전검사 (kb_content 모드 — consultation_seed는 _PUBLIC_SOURCES에 포함)
            violations = precheck_violations(faq["content"], source_id="consultation_seed")
            if violations:
                logger.warning("SKIP %s: 위반=%s", faq["title"], violations)
                skipped += 1
                continue

            result = ingest_document(
                title=faq["title"],
                content_md=faq["content"],
                source_id="consultation_seed",
                metadata={
                    "evidence_level": "A",
                    "symptom_tags": faq["symptom_tags"],
                    "severity": "emergency" if "심정지" in faq["title"] or "CPR" in faq["title"] else "moderate",
                },
                evidence_country="KR",
                evidence_topic=faq["evidence_topic"],
                regulatory_korea=True,
                topic_keywords=faq["symptom_tags"],
                status="active",
                upsert=True,
            )
            doc_id_short = (result.get("document_id") or "")[:8]
            chunks_count = result.get("chunks_count", 0)
            status_str = result.get("status", "?")
            print(f"OK  [{status_str}] {faq['title']} => doc={doc_id_short}, chunks={chunks_count}")
            success += 1
        except Exception:
            logger.exception("실패: %s", faq["title"])
            failed += 1

    print(f"\n{'='*60}")
    print(f"  완료: success={success}, skipped={skipped}, failed={failed}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
