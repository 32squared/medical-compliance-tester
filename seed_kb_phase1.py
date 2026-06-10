"""
KB 시드 생성 스크립트 — Phase 1
==============================
consultation_checklists.json (42개 증상) + guidelines.json (9개 금지규칙)
을 KB 문서로 변환·ingest한다.

실행:
    python seed_kb_phase1.py
    python seed_kb_phase1.py --upsert      # 기존 문서 덮어쓰기
    python seed_kb_phase1.py --dry-run     # 마크다운만 생성, DB 저장 생략

Cloud Run Job 환경에서는 DATABASE_URL 환경변수가 반드시 필요.
OPENAI_API_KEY 없으면 임베딩을 생략하고 텍스트 인덱스만 구축한다.
"""

import io
import os
import sys
import json
import time
import logging
import argparse

# 한글 출력 보장
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 프로젝트 루트를 sys.path 에 추가
_REPO_ROOT = os.path.dirname(os.path.abspath(__file__))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────
#  증상 → 진료과 매핑표
# ────────────────────────────────────────────
_DEPT_MAP = {
    "fever": "내과",
    "fatigue": "내과",
    "weight_change": "내과",
    "body_pain": "가정의학과",
    "headache": "신경과",
    "dizziness": "신경과",
    "memory_loss": "신경과",
    "numbness": "신경과",
    "seizure": "신경과",
    "vision_loss": "안과",
    "eye_pain": "안과",
    "ear_pain": "이비인후과",
    "nasal_congestion": "이비인후과",
    "throat_pain": "이비인후과",
    "cough": "내과",
    "dyspnea": "내과",
    "chest_pain_resp": "내과",
    "abdominal_pain": "내과",
    "heartburn": "내과",
    "diarrhea": "내과",
    "constipation": "내과",
    "bloody_stool": "내과",
    "chest_pain": "순환기내과",
    "palpitation": "순환기내과",
    "leg_edema": "순환기내과",
    "bp_abnormal": "순환기내과",
    "back_pain": "정형외과",
    "knee_pain": "정형외과",
    "shoulder_pain": "정형외과",
    "myalgia": "재활의학과",
    "dysuria": "비뇨기과",
    "frequency": "비뇨기과",
    "hematuria": "비뇨기과",
    "menstrual": "산부인과",
    "rash": "피부과",
    "itching": "피부과",
    "acne": "피부과",
    "skin_tumor": "피부과",
    "anxiety": "정신건강의학과",
    "depression": "정신건강의학과",
    "insomnia": "정신건강의학과",
    "stress": "정신건강의학과",
}

# emergency 수준 판별 키워드 (red_flag label 기준)
_EMERGENCY_KEYWORDS = [
    "응급", "119", "심정지", "경련", "의식", "호흡곤란", "고열",
    "출혈", "마비", "쓰러", "심근경색", "뇌졸중",
]

# ────────────────────────────────────────────
#  가이드라인 카테고리 한국어 레이블
# ────────────────────────────────────────────
_GUIDELINE_CATEGORY_LABELS = {
    "diagnosis": "병명 단정 및 확정 진단 금지",
    "prescription": "처방·복약·용량 관련 지시 금지",
    "test_procedure": "검사·시술·치료 관련 지시 금지",
    "emergency_dismiss": "응급·내원 필요성 단정 부정 금지",
    "personalized_treatment": "개인 맞춤 치료 계획·목표 설정 금지",
    "risk_probability": "위험도·사망률·질병 확률 제시 금지",
    "post_procedure_advice": "시술 후 의학적 관리 지시 금지",
    "hospital_referral": "특정 병원·의사 유인·알선 금지",
    "impersonation": "의료 전문가 사칭·대리진료 암시 금지",
}

_GUIDELINE_TOPIC_KEYWORDS_MAP = {
    "diagnosis": ["진단", "병명", "확정", "의료법 제27조", "무면허 의료행위", "병명 단정"],
    "prescription": ["처방", "복약", "용량", "약물", "의료법 제27조", "항생제", "인슐린"],
    "test_procedure": ["검사", "시술", "치료", "CT", "MRI", "내시경", "수술", "물리치료"],
    "emergency_dismiss": ["응급", "119", "응급실", "내원", "응급의료법", "경과 관찰"],
    "personalized_treatment": ["치료 계획", "혈당 목표", "혈압 목표", "개인 맞춤", "의료법 제27조"],
    "risk_probability": ["위험도", "사망률", "확률", "암 위험", "치매", "대사증후군"],
    "post_procedure_advice": ["시술 후", "수술 후", "부작용", "의학적 관리", "의료법 제27조"],
    "hospital_referral": ["병원 추천", "의사 알선", "특정 병원", "의료법 제56조", "유인"],
    "impersonation": ["사칭", "대리진료", "처방전", "진단서", "의료 전문가"],
}


# ════════════════════════════════════════════
#  Part A: consultation_checklists.json → 마크다운
# ════════════════════════════════════════════

def _build_checklist_markdown(symptom: dict) -> str:
    """증상 체크리스트 1개를 마크다운 문자열로 변환."""
    key = symptom["symptom_key"]
    name_ko = symptom.get("symptom_name") or symptom.get("symptom_name_ko") or key
    detail = symptom.get("detail", "")
    department = symptom.get("department", _DEPT_MAP.get(key, "내과"))

    required_qs = symptom.get("required_questions", [])
    red_flags = symptom.get("red_flags", [])
    context_qs = symptom.get("context_questions", [])
    age_specific = symptom.get("age_specific", {})

    lines = []

    # ── H1 제목 ──
    lines.append(f"# {name_ko} ({key})")
    lines.append("")

    # ── 정의 및 개요 ──
    lines.append("## 정의 및 개요")
    desc = f"{name_ko}"
    if detail:
        desc += f" — {detail}"
    lines.append(
        f"{desc}에 대한 문진 평가는 다음과 같은 단계로 이루어집니다. "
        f"담당 진료과: {department}."
    )
    lines.append("")

    # ── 필수 확인 항목 ──
    lines.append("## 필수 확인 항목")
    if required_qs:
        for q in required_qs:
            label = q.get("label", "")
            kws = q.get("keywords", [])
            kw_str = ", ".join(kws) if kws else ""
            if kw_str:
                lines.append(f"- {label} (키워드: {kw_str})")
            else:
                lines.append(f"- {label}")
    else:
        lines.append("- 증상 발현 시점 및 지속 기간")
        lines.append("- 악화·완화 요인")
    lines.append("")

    # ── Red Flags ──
    lines.append("## 위험 신호 (Red Flags) — 응급 가능성")
    if red_flags:
        for rf in red_flags:
            label = rf.get("label", "")
            kws = rf.get("keywords", [])
            kw_str = ", ".join(kws) if kws else ""
            if kw_str:
                lines.append(f"- {label} (관련 키워드: {kw_str})")
            else:
                lines.append(f"- {label}")
    else:
        lines.append("- 증상이 갑작스럽게 악화되거나 의식 변화 동반 시 즉시 응급 처치 필요")
    lines.append("")

    # ── 상황 및 배경 정보 ──
    lines.append("## 상황 및 배경 정보")
    if context_qs:
        for cq in context_qs:
            label = cq.get("label", "")
            kws = cq.get("keywords", [])
            kw_str = ", ".join(kws) if kws else ""
            if kw_str:
                lines.append(f"- {label} (키워드: {kw_str})")
            else:
                lines.append(f"- {label}")
    else:
        lines.append("- 복용 중인 약물 및 기저질환 확인")
    lines.append("")

    # ── 연령별 특이사항 ──
    if age_specific:
        lines.append("## 연령별 특이사항")
        age_labels = {
            "child": "소아 (12세 이하)",
            "teen": "청소년 (13~18세)",
            "young": "청년 (19~39세)",
            "middle": "중년 (40~64세)",
            "senior": "노년 (65세 이상)",
        }
        for age_key, age_label in age_labels.items():
            if age_key in age_specific:
                group = age_specific[age_key]
                items = group.get("items", [])
                if items:
                    lines.append(f"### {age_label}")
                    for item in items:
                        lines.append(f"- {item}")
                    lines.append("")

    # ── 권장 다음 단계 ──
    lines.append("## 권장 다음 단계")
    lines.append(
        "- 위험 신호(Red Flag) 발견 시: 119 또는 응급실 방문을 즉시 안내"
    )
    lines.append(
        f"- 일반 증상 지속 시: {department} 전문의 상담 권장"
    )
    lines.append(
        "- 자가 관리 가능 수준: 증상 경과 관찰 후 악화 시 의료기관 방문 권고"
    )
    lines.append(
        "- 본 안내는 의료적 진단을 의미하지 않으며 참고용입니다."
    )
    lines.append("")

    return "\n".join(lines)


def _checklist_severity(symptom: dict) -> str:
    """red_flags에 emergency 키워드 포함 여부로 severity 결정."""
    red_flags = symptom.get("red_flags", [])
    all_text = " ".join(
        " ".join([rf.get("label", "")] + rf.get("keywords", []))
        for rf in red_flags
    )
    for kw in _EMERGENCY_KEYWORDS:
        if kw in all_text:
            return "emergency"
    if red_flags:
        return "moderate"
    return "low"


def build_checklist_docs(checklists: list, upsert: bool = False) -> list:
    """
    consultation_checklists.json → ingest_batch() 입력 형식 dict 리스트 반환.
    """
    docs = []
    for symptom in checklists:
        key = symptom["symptom_key"]
        name_ko = symptom.get("symptom_name") or key
        department = symptom.get("department", _DEPT_MAP.get(key, "내과"))
        severity = _checklist_severity(symptom)

        content_md = _build_checklist_markdown(symptom)

        # topic_keywords: 증상명 + required/red_flag 키워드 상위 수집
        kw_set = {name_ko, key}
        for q in symptom.get("required_questions", []):
            kw_set.update(q.get("keywords", []))
        for rf in symptom.get("red_flags", []):
            kw_set.update(rf.get("keywords", []))
        # 너무 짧은 키워드(1글자) 제외
        topic_keywords = sorted(kw for kw in kw_set if len(kw) > 1)

        docs.append({
            "title": f"{name_ko} ({key}) 문진 체크리스트",
            "content_md": content_md,
            "source_id": "consultation_seed",
            "metadata": {
                "evidence_level": "A",
                "symptom_tags": [key],
                "severity": severity,
                "department": department,
                "category": symptom.get("category", ""),
            },
            "evidence_country": "KR",
            "evidence_topic": key,
            "regulatory_korea": False,
            "topic_keywords": topic_keywords,
            "upsert": upsert,
            "status": "active",
        })

    return docs


# ════════════════════════════════════════════
#  Part B: guidelines.json → 마크다운
# ════════════════════════════════════════════

def _build_guideline_markdown(rule: dict, fixed_notices: dict) -> str:
    """금지규칙 1개를 마크다운 문서로 변환."""
    rule_id = rule["id"]
    category = rule.get("category", "")
    category_label = _GUIDELINE_CATEGORY_LABELS.get(rule_id, category)
    severity = rule.get("severity", "HIGH")
    law = rule.get("law", "의료법")
    description = rule.get("description", "")
    examples = rule.get("examples", [])

    bottom_disclaimer = fixed_notices.get("bottom_disclaimer", "의료진과 상담하세요.")
    non_medical = fixed_notices.get("non_medical_notice", "")
    emergency_notice = fixed_notices.get("emergency_notice", "")

    lines = []

    # ── H1 ──
    lines.append(f"# 의료법 가이드 — {category_label}")
    lines.append("")

    # ── 근거 ──
    lines.append("## 근거")
    lines.append(f"- 법령: {law}")
    lines.append(f"- 위반 심각도: {severity}")
    lines.append(f"- 설명: {description}")
    lines.append("")

    # ── 금지 패턴 ──
    lines.append("## 금지 표현 패턴")
    if examples:
        for ex in examples:
            lines.append(f"- {ex}")
    else:
        lines.append("- 해당 카테고리의 구체적 금지 표현 목록을 참고하세요.")
    lines.append("")

    # ── 올바른 표현 예시 (고정) ──
    lines.append("## 올바른 대응 원칙")
    lines.append(
        "- 의료적 진단·처방·치료 지시 없이 일반적 건강정보만 제공한다."
    )
    lines.append(
        "- 증상 관련 일반 정보를 제공하되 '가능성이 있습니다', '의료진과 상담하세요' 표현 사용."
    )
    lines.append(
        "- 응급 증상(흉통·호흡곤란·의식 변화 등) 언급 시 즉시 119 또는 응급실 안내."
    )
    lines.append(
        "- 약물·검사·시술 관련 결정은 반드시 의료진에게 위임."
    )
    lines.append("")

    # ── 면책조항 ──
    lines.append("## 면책조항")
    if non_medical:
        lines.append(f"- {non_medical}")
    if emergency_notice:
        lines.append(f"- {emergency_notice}")
    lines.append(f"- {bottom_disclaimer}")
    lines.append("")

    return "\n".join(lines)


def build_guideline_docs(guidelines_data: dict, upsert: bool = False) -> list:
    """
    guidelines.json → ingest_batch() 입력 형식 dict 리스트 반환.
    prohibited_rules 9개 각각을 1개 KB 문서로 변환.
    """
    fixed_notices = guidelines_data.get("fixed_notices", {})
    prohibited_rules = guidelines_data.get("prohibited_rules", [])

    docs = []
    for rule in prohibited_rules:
        rule_id = rule["id"]
        category_label = _GUIDELINE_CATEGORY_LABELS.get(rule_id, rule.get("category", ""))
        topic_keywords = _GUIDELINE_TOPIC_KEYWORDS_MAP.get(rule_id, [rule_id])

        content_md = _build_guideline_markdown(rule, fixed_notices)

        docs.append({
            "title": f"의료법 가이드 — {category_label}",
            "content_md": content_md,
            "source_id": "guideline_internal",
            "metadata": {
                "evidence_level": "A",
                "rule_id": rule_id,
                "severity": rule.get("severity", "HIGH"),
                "law": rule.get("law", "의료법 제27조"),
            },
            "evidence_country": "KR",
            "evidence_topic": rule_id,
            "regulatory_korea": True,
            "topic_keywords": topic_keywords,
            "upsert": upsert,
            "status": "active",
        })

    return docs


# ════════════════════════════════════════════
#  Part C: kb_sources 시드 INSERT
# ════════════════════════════════════════════

def seed_phase1_sources() -> int:
    """
    consultation_seed, guideline_internal 소스를 kb_sources에 사전 등록.
    이미 존재하면 SKIP (멱등).
    """
    from kb_ingest import seed_kb_sources

    now_sources = [
        {
            "id": "consultation_seed",
            "name": "자체 제작 증상 문진 체크리스트 (의사 자문 반영)",
            "source_type": "internal",
            "license": "proprietary",
            "update_frequency": "on_demand",
            "is_active": 1,
        },
        {
            "id": "guideline_internal",
            "name": "의료법 준수 가이드라인 (나만의 주치의 내부 기준)",
            "source_type": "guideline",
            "license": "proprietary",
            "update_frequency": "on_demand",
            "is_active": 1,
        },
    ]
    inserted = seed_kb_sources(now_sources)
    logger.info("[Seed] kb_sources 삽입: %d건", inserted)
    return inserted


# ════════════════════════════════════════════
#  검증 쿼리
# ════════════════════════════════════════════

def _row_count(row) -> int:
    """PostgreSQL(RealDictRow) / SQLite(tuple) 양쪽 count 추출."""
    if row is None:
        return 0
    if isinstance(row, dict):
        # RealDictCursor: 첫 번째 값 반환
        return int(list(row.values())[0])
    # SQLite tuple/Row
    return int(row[0])


def verify_ingest() -> dict:
    """ingest 결과 DB 검증."""
    from db import get_conn, _use_postgres

    reg_filter = "TRUE" if _use_postgres else "1"

    with get_conn() as (conn, cur):
        cur.execute("SELECT COUNT(*) FROM kb_documents WHERE status='active'")
        docs = _row_count(cur.fetchone())

        cur.execute("SELECT COUNT(*) FROM kb_chunks")
        chunks = _row_count(cur.fetchone())

        cur.execute("SELECT COUNT(DISTINCT source_id) FROM kb_documents")
        sources = _row_count(cur.fetchone())

        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks WHERE evidence_country='KR'"
        )
        kr_chunks = _row_count(cur.fetchone())

        cur.execute(
            f"SELECT COUNT(*) FROM kb_chunks WHERE regulatory_korea={reg_filter}"
        )
        reg_chunks = _row_count(cur.fetchone())

    return {
        "docs": docs,
        "chunks": chunks,
        "sources": sources,
        "kr_chunks": kr_chunks,
        "reg_chunks": reg_chunks,
    }


# ════════════════════════════════════════════
#  메인
# ════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="KB 시드 Phase 1: consultation_checklists + guidelines ingest"
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="기존 문서 덮어쓰기 (중복 시 UPDATE, 기본 SKIP)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="마크다운만 생성·출력, DB 저장 생략",
    )
    parser.add_argument(
        "--only",
        choices=["checklist", "guideline"],
        default=None,
        help="특정 파트만 실행 (기본: 전체)",
    )
    args = parser.parse_args()

    # ── JSON 로드 (로더 위임 — packages/medical_shared/compliance_rules 번들 읽기) ──
    import consultation_loader
    import guideline_loader
    checklists = consultation_loader.load_checklists_raw()
    guidelines_data = guideline_loader.load_guidelines()

    logger.info("[Seed] consultation_checklists.json 로드: %d개 증상", len(checklists))
    logger.info(
        "[Seed] guidelines.json 로드: %d개 금지규칙",
        len(guidelines_data.get("prohibited_rules", [])),
    )

    # ── dry-run 모드: 마크다운만 출력 ──
    if args.dry_run:
        logger.info("[DryRun] 마크다운 샘플 출력 (첫 2개 증상 + 첫 2개 가이드라인)")
        sample_symptom_docs = build_checklist_docs(checklists[:2], upsert=False)
        for doc in sample_symptom_docs:
            print("=" * 60)
            print(f"TITLE: {doc['title']}")
            print(f"SOURCE_ID: {doc['source_id']}")
            print(f"EVIDENCE_TOPIC: {doc['evidence_topic']}")
            print(f"TOPIC_KEYWORDS: {doc['topic_keywords']}")
            print("-" * 40)
            print(doc["content_md"])
        sample_guide_docs = build_guideline_docs(guidelines_data, upsert=False)
        for doc in sample_guide_docs[:2]:
            print("=" * 60)
            print(f"TITLE: {doc['title']}")
            print(f"SOURCE_ID: {doc['source_id']}")
            print(f"REGULATORY_KOREA: {doc['regulatory_korea']}")
            print("-" * 40)
            print(doc["content_md"])
        logger.info("[DryRun] 완료. DB 저장 없음.")
        return

    # ── 실제 ingest ──
    from db import init_db
    from kb_ingest import ingest_batch

    logger.info("[Seed] DB 초기화...")
    init_db()

    # Part C: kb_sources 시드
    logger.info("[Seed] Part C: kb_sources 시드 INSERT...")
    seed_phase1_sources()

    t_total_start = time.time()
    all_docs = []

    if args.only in (None, "checklist"):
        logger.info("[Seed] Part A: 증상 체크리스트 %d개 문서 생성...", len(checklists))
        checklist_docs = build_checklist_docs(checklists, upsert=args.upsert)
        all_docs.extend(checklist_docs)
        logger.info("[Seed] Part A: %d개 문서 준비 완료", len(checklist_docs))

    if args.only in (None, "guideline"):
        n_rules = len(guidelines_data.get("prohibited_rules", []))
        logger.info("[Seed] Part B: 가이드라인 금지규칙 %d개 문서 생성...", n_rules)
        guideline_docs = build_guideline_docs(guidelines_data, upsert=args.upsert)
        all_docs.extend(guideline_docs)
        logger.info("[Seed] Part B: %d개 문서 준비 완료", len(guideline_docs))

    logger.info("[Seed] 총 %d개 문서 ingest 시작...", len(all_docs))
    result = ingest_batch(all_docs)

    t_elapsed = time.time() - t_total_start
    total_chunks = sum(r.get("chunks_count", 0) for r in result["results"])

    # ── 검증 ──
    logger.info("[Seed] DB 검증 중...")
    verify = verify_ingest()

    # ── 결과 출력 ──
    print("")
    print("=" * 60)
    print("  KB 시드 Phase 1 ingest 결과")
    print("=" * 60)
    print(f"  총 문서 준비:       {len(all_docs)}개")
    print(f"  ingest 성공:        {result['success']}개")
    print(f"  ingest 실패:        {result['failed']}개")
    print(f"  생성된 청크:        {total_chunks}개")
    print(f"  실행 시간:          {t_elapsed:.1f}초 ({t_elapsed/60:.1f}분)")
    print("")
    print("  [DB 검증]")
    print(f"  kb_documents (active):    {verify['docs']}행")
    print(f"  kb_chunks 전체:           {verify['chunks']}행")
    print(f"  kb_sources 종류:          {verify['sources']}개")
    print(f"  evidence_country=KR:      {verify['kr_chunks']}청크")
    print(f"  regulatory_korea=true:    {verify['reg_chunks']}청크")
    print("")

    # 기대값 체크
    ok = True
    if verify["docs"] < 47:
        print(f"  [WARN] docs < 47 (현재 {verify['docs']}). 일부 누락 가능.")
        ok = False
    if verify["chunks"] < 100:
        print(f"  [WARN] chunks < 100 (현재 {verify['chunks']}). 청킹 확인 필요.")
        ok = False
    if verify["sources"] < 2:
        print(f"  [WARN] sources < 2 (현재 {verify['sources']}). kb_sources 확인 필요.")
        ok = False

    if result["errors"]:
        print("  [ERRORS]")
        for err in result["errors"]:
            print(f"    - {err}", file=sys.stderr)

    if ok and result["failed"] == 0:
        print("  [OK] 모든 검증 통과.")
    print("=" * 60)

    sys.exit(1 if result["failed"] > 0 else 0)


if __name__ == "__main__":
    main()
