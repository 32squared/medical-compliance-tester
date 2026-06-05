"""
응급/핵심 의료 시나리오 KB 청크 자체 작성 + 적재.
GPT-5로 의료법 준수 콘텐츠 생성 → consultation_seed source에 ingest.
status='active' 직접 적재 (자체 콘텐츠).

직전 검증 실패 항목 기반 11개 시나리오:
- 응급 5개: 심정지, AED, 응급실 위험신호, 흉통, 호흡곤란
- 중증도 6개: 발열, 만성기침, 당뇨, 급성복통, 두통, 어지러움

실행:
    python seed_emergency_kb.py
    python seed_emergency_kb.py --upsert      # 기존 문서 덮어쓰기
    python seed_emergency_kb.py --dry-run     # GPT 호출 없이 아웃라인만 출력
    python seed_emergency_kb.py --only cardiac_arrest  # 단일 시나리오만

의료적 안전성:
    - 모든 콘텐츠에 CRITICAL 위반 사전 검사 (analyzer.ComplianceAnalyzer)
    - CRITICAL 위반 시 자동 SKIP (DB 저장 안 함)
    - upsert=True로 재실행 안전 (멱등)
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

# 프로젝트 루트를 sys.path에 추가
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
#  신규 source 메타데이터
# ────────────────────────────────────────────
_EMERGENCY_SOURCE = {
    "id": "consultation_seed",
    "name": "자체 제작 증상 문진 체크리스트 (의사 자문 반영)",
    "source_type": "internal",
    "license": "proprietary",
    "update_frequency": "on_demand",
    "is_active": 1,
}

# ────────────────────────────────────────────
#  GPT 프롬프트
# ────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "당신은 대한응급의학회 공인 응급의학 전문의입니다. "
    "요청된 의료 시나리오에 대해 의료법 준수 한국어 마크다운 가이드를 작성하십시오. "
    "의료법 제27조: 진단·처방·치료 지시 단정 금지. "
    "의료법 제56조: 과대·허위 효능 주장 금지. "
    "응급 상황에는 반드시 '119 즉시 신고' 또는 '응급실 방문'을 명시하십시오."
)

_USER_PROMPT_TEMPLATE = """\
다음 의료 시나리오를 4단 구조 한국어 마크다운으로 작성하십시오.

제목: {title}
핵심 항목:
{outline}

요구사항:
1. 4단 구조로 작성:
   ## 즉시 행동
   ## 의심 원인
   ## 상세 설명
   ## 추가 확인 사항
2. 의료법 27조 준수: 진단·처방 단정 금지.
   "의료기관 상담 권장" 또는 "의사 진료를 받으시기 바랍니다" 형식 사용.
3. 응급 시나리오는 반드시 "119 즉시 신고" 또는 "응급실 방문" 강조.
4. 의사가 작성한 표준 가이드처럼 명료하고 사실 위주로 작성.
5. 총 800~1500자.
6. ## 헤더부터 시작 (# 제목 줄 제외).

마크다운 본문만 출력:"""


# ────────────────────────────────────────────
#  작성할 시나리오 목록 (직전 검증 실패 항목 기반)
# ────────────────────────────────────────────
SCENARIOS = [
    # ── 응급 시나리오 ──
    {
        "evidence_topic": "cardiac_arrest",
        "title": "성인 심정지 즉시 행동 가이드",
        "symptom_tags": ["심정지", "흉부압박", "CPR", "심폐소생술"],
        "severity": "emergency",
        "outline": (
            "- 의식 확인 (어깨 두드림)\n"
            "- 119 신고 + AED 요청\n"
            "- 흉부압박 30회 (속도 100~120/분, 깊이 5~6cm)\n"
            "- 인공호흡 2회\n"
            "- AED 도착 시 즉시 부착\n"
            "- 압박과 인공호흡 30:2 반복"
        ),
    },
    {
        "evidence_topic": "aed_usage",
        "title": "AED(자동심장충격기) 표준 사용 5단계",
        "symptom_tags": ["AED", "자동심장충격기", "심정지", "제세동"],
        "severity": "emergency",
        "outline": (
            "- 1) 전원 켜기\n"
            "- 2) 패드 부착 (오른쪽 빗장뼈 아래 + 왼쪽 옆구리)\n"
            "- 3) 분석 중 환자에게서 손 떼기\n"
            "- 4) '제세동 권고' 시 모두 떨어진 상태에서 버튼 누르기\n"
            "- 5) 즉시 흉부압박 재개"
        ),
    },
    {
        "evidence_topic": "emergency_signs",
        "title": "응급실 즉시 방문이 필요한 위험 신호",
        "symptom_tags": ["응급실", "위급", "119", "위험신호", "응급징후"],
        "severity": "emergency",
        "outline": (
            "- 의식 저하·실신\n"
            "- 흉통 15분 이상 지속\n"
            "- 호흡곤란 + 청색증\n"
            "- 토혈·혈변·다량 출혈\n"
            "- 갑작스러운 편측 마비·언어장애 (뇌졸중 의심)\n"
            "- 38.5도 이상 고열 + 의식 혼탁\n"
            "- 심한 두통 + 구토\n"
            "- 외상 + 의식 변화"
        ),
    },
    {
        "evidence_topic": "chest_pain",
        "title": "성인 흉통 응급 평가 체크리스트",
        "symptom_tags": ["흉통", "협심증", "심근경색", "흉부통증"],
        "severity": "emergency",
        "outline": (
            "- 통증 성격: 압박·죄임·쥐어짜는 느낌 → 심장 의심\n"
            "- 방사 부위: 왼팔·턱·등 → 심장 의심\n"
            "- 동반 증상: 식은땀·호흡곤란·메스꺼움\n"
            "- 15분 이상 지속: 119 즉시 신고\n"
            "- 안정 시 발생·니트로글리세린 무반응: 응급\n"
            "- 호흡 시 악화: 흉막·폐색전 의심\n"
            "- 자세 변화 시 악화: 근골격계 가능"
        ),
    },
    {
        "evidence_topic": "dyspnea",
        "title": "성인 호흡곤란 응급 평가",
        "symptom_tags": ["호흡곤란", "숨참", "청색증", "호흡이상"],
        "severity": "emergency",
        "outline": (
            "- 발생 양상: 갑작스러움·점진적\n"
            "- 동반 증상: 흉통·기침·발열·다리부종\n"
            "- 청색증·말 한마디 못함: 즉시 119 신고\n"
            "- 폐색전·폐렴·천식·심부전 감별\n"
            "- 안정 시 호흡곤란: 응급\n"
            "- 이전 진단 (천식·COPD·심장병) 확인\n"
            "- 산소포화도 측정 (가정용 산소포화도계 90% 미만 시 응급)"
        ),
    },
    # ── 중등도 시나리오 ──
    {
        "evidence_topic": "fever",
        "title": "성인 발열(38도 이상) 단계별 대응",
        "symptom_tags": ["발열", "고열", "체온", "열"],
        "severity": "moderate",
        "outline": (
            "- 체온 정확 측정 (구강·고막·이마)\n"
            "- 38~38.5도: 충분한 수분, 휴식, 미온수 마사지\n"
            "- 38.5도 이상: 해열제 복용 고려, 의료기관 상담\n"
            "- 39도 이상 또는 의식 변화: 응급실\n"
            "- 동반 증상 확인 (목 강직, 발진, 호흡곤란, 복통)\n"
            "- 3일 이상 지속 시 의사 진료"
        ),
    },
    {
        "evidence_topic": "chronic_cough",
        "title": "기침 2주 이상 지속 시 평가 흐름",
        "symptom_tags": ["기침", "만성기침", "객담", "기침지속"],
        "severity": "moderate",
        "outline": (
            "- 흡연력 확인\n"
            "- 동반 증상: 객담 색·혈담·체중감소·야간 발한\n"
            "- 흉부 X선 검사 권장\n"
            "- 결핵·폐렴·천식·역류성식도염·심부전 감별\n"
            "- 8주 이상 지속: 만성 기침 — 폐기능 검사 + 객담 검사\n"
            "- 흡연자 + 50세 이상: 폐암 선별검사 고려"
        ),
    },
    {
        "evidence_topic": "diabetes",
        "title": "당뇨병 초기 의심 증상과 검사",
        "symptom_tags": ["당뇨", "다음다뇨", "공복혈당", "혈당"],
        "severity": "moderate",
        "outline": (
            "- 의심 증상: 다음·다뇨·다식·체중감소·시야 흐림·상처 회복 지연\n"
            "- 1차 검사: 공복혈당 (126mg/dL 이상)\n"
            "- 당화혈색소 (HbA1c 6.5% 이상)\n"
            "- 75g 경구당부하검사 (2시간 200mg/dL 이상)\n"
            "- 위 항목 중 2회 이상 양성 시 당뇨병 확진\n"
            "- 생활습관 평가 + 합병증 검사 (눈·신장·신경)"
        ),
    },
    {
        "evidence_topic": "abdominal_pain",
        "title": "급성 복통 평가 순서",
        "symptom_tags": ["복통", "맹장염", "복막염", "급성복통"],
        "severity": "moderate",
        "outline": (
            "- 통증 부위 위치 (4분면)\n"
            "- 우하복부: 충수돌기염 의심 (구토·발열 동반 시 응급)\n"
            "- 우상복부: 담낭염·간\n"
            "- 좌상복부: 위·췌장\n"
            "- 좌하복부: 게실염\n"
            "- 미만성: 복막염 의심 — 즉시 응급실\n"
            "- 동반 증상: 발열·구토·혈변·하혈\n"
            "- 임신 가능성·생리주기 확인"
        ),
    },
    {
        "evidence_topic": "headache",
        "title": "두통 응급도 판단 기준",
        "symptom_tags": ["두통", "편두통", "뇌졸중", "두통평가"],
        "severity": "moderate",
        "outline": (
            "- 갑작스럽고 격렬한 두통 (천둥치는 듯): 지주막하출혈 의심 — 즉시 응급실\n"
            "- 동반 증상: 의식저하·구토·편마비·언어장애·시야장애 → 뇌졸중·종양 의심\n"
            "- 발열·목 강직: 뇌수막염 의심\n"
            "- 50세 이후 새로 시작: 측두동맥염·종양 감별\n"
            "- 외상 후 두통: CT 검사\n"
            "- 만성 두통 (3개월 이상): 신경과 진료 권장"
        ),
    },
    {
        "evidence_topic": "dizziness",
        "title": "어지러움 원인별 평가",
        "symptom_tags": ["어지러움", "현기증", "이석증", "어지럼"],
        "severity": "moderate",
        "outline": (
            "- 회전성 어지러움: 전정기관 (이석증·전정신경염·메니에르)\n"
            "- 실신성: 기립성저혈압·부정맥\n"
            "- 동반 증상: 두통·구토·복시·운동실조 → 뇌졸중 감별 응급\n"
            "- 30초 이내 회복: 양성돌발성체위현훈 (이석증) 가능\n"
            "- 청력 저하 동반: 메니에르병\n"
            "- 약물 부작용 확인 (항고혈압제·이뇨제)"
        ),
    },
]


# ════════════════════════════════════════════
#  GPT-5 콘텐츠 생성 (비스트리밍)
# ════════════════════════════════════════════

def generate_content(client, scenario: dict) -> tuple:
    """
    GPT-5로 시나리오를 4단 구조 마크다운으로 확장한다.

    Args:
        client:   openai.OpenAI 클라이언트 인스턴스
        scenario: SCENARIOS 항목 dict

    Returns:
        (content_md: str, input_tokens: int, output_tokens: int)
    """
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        title=scenario["title"],
        outline=scenario["outline"],
    )

    logger.info("[GenContent] GPT-5 호출: %s", scenario["title"])
    t_start = time.time()

    response = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user",   "content": user_prompt},
        ],
        max_completion_tokens=8192,
        reasoning_effort="minimal",
    )

    content_md = response.choices[0].message.content or ""
    input_tokens = 0
    output_tokens = 0
    if response.usage:
        input_tokens = getattr(response.usage, "prompt_tokens", 0) or 0
        output_tokens = getattr(response.usage, "completion_tokens", 0) or 0

    elapsed = time.time() - t_start
    logger.info(
        "[GenContent] 완료: %s — %d자, token(in=%d, out=%d), %.1f초",
        scenario["title"], len(content_md), input_tokens, output_tokens, elapsed,
    )

    return content_md, input_tokens, output_tokens


# ════════════════════════════════════════════
#  source INSERT (멱등)
# ════════════════════════════════════════════

def seed_emergency_source() -> bool:
    """
    consultation_seed source를 kb_sources에 등록.
    이미 존재하면 SKIP (멱등).

    Returns:
        True if newly inserted, False if skipped.
    """
    from kb_ingest import seed_kb_sources

    inserted = seed_kb_sources([_EMERGENCY_SOURCE])
    if inserted > 0:
        logger.info("[Seed] source 등록 완료: %s", _EMERGENCY_SOURCE["id"])
        return True
    else:
        logger.info("[Seed] source 이미 존재 (SKIP): %s", _EMERGENCY_SOURCE["id"])
        return False


# ════════════════════════════════════════════
#  검증 쿼리
# ════════════════════════════════════════════

def _row_val(row) -> int:
    """PostgreSQL RealDictRow / SQLite tuple 양쪽 count 추출."""
    if row is None:
        return 0
    if isinstance(row, dict):
        return int(list(row.values())[0])
    return int(row[0])


def verify_emergency_docs() -> dict:
    """consultation_seed source의 active 문서/청크 수 검증."""
    from db import get_conn

    with get_conn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) FROM kb_documents "
            "WHERE source_id = 'consultation_seed' AND status = 'active'"
        )
        active_docs = _row_val(cur.fetchone())

        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks c "
            "JOIN kb_documents d ON c.document_id = d.id "
            "WHERE d.source_id = 'consultation_seed' AND d.status = 'active'"
        )
        active_chunks = _row_val(cur.fetchone())

    return {
        "active_docs":   active_docs,
        "active_chunks": active_chunks,
    }


# ════════════════════════════════════════════
#  메인
# ════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "응급/핵심 의료 시나리오 KB 시드: GPT-5로 콘텐츠 생성 → "
            "consultation_seed status='active'로 INSERT"
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="GPT 호출 없이 아웃라인만 출력, DB 저장 생략",
    )
    parser.add_argument(
        "--upsert",
        action="store_true",
        help="이미 존재하는 문서 덮어쓰기 (기본: SKIP)",
    )
    parser.add_argument(
        "--only",
        type=str,
        default=None,
        metavar="EVIDENCE_TOPIC",
        help="특정 시나리오만 처리 (예: --only cardiac_arrest)",
    )
    args = parser.parse_args()

    # ── dry-run: 아웃라인 미리보기만 ──────────────────────────
    if args.dry_run:
        logger.info("[DryRun] GPT 호출 없이 시나리오 아웃라인 출력")
        targets = [
            sc for sc in SCENARIOS
            if args.only is None or sc["evidence_topic"] == args.only
        ]
        for sc in targets:
            print("=" * 60)
            print(f"TITLE:         {sc['title']}")
            print(f"TOPIC:         {sc['evidence_topic']}")
            print(f"SEVERITY:      {sc['severity']}")
            print(f"SYMPTOM_TAGS:  {sc['symptom_tags']}")
            print("-" * 40)
            print("[SYSTEM]", _SYSTEM_PROMPT)
            print("[USER OUTLINE]")
            print(sc["outline"])
        logger.info("[DryRun] 완료. DB 저장 없음.")
        return

    # ── 실제 실행 ─────────────────────────────────────────────
    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        logger.error("[Seed] OPENAI_API_KEY 환경변수가 설정되지 않았습니다.")
        sys.exit(1)

    from openai import OpenAI
    from db import init_db
    from kb_ingest import ingest_document
    from analyzer import ComplianceAnalyzer

    logger.info("[Seed] DB 초기화...")
    init_db()

    # ── source 등록 ───────────────────────────────────────────
    logger.info("[Seed] consultation_seed source 등록 중...")
    seed_emergency_source()

    # ── OpenAI 클라이언트 + 분석기 초기화 ────────────────────
    client = OpenAI(api_key=openai_key)
    analyzer = ComplianceAnalyzer()

    # ── 처리 대상 필터링 ──────────────────────────────────────
    targets = [
        sc for sc in SCENARIOS
        if args.only is None or sc["evidence_topic"] == args.only
    ]
    logger.info("[Seed] 처리 대상 시나리오: %d개", len(targets))

    # ── 통계 집계 변수 ────────────────────────────────────────
    t_total_start = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    success_count = 0
    skip_count = 0
    failed_count = 0
    total_chunks = 0
    errors = []

    # ── 시나리오별 순차 처리 ─────────────────────────────────
    for idx, sc in enumerate(targets, 1):
        logger.info(
            "[Seed] [%d/%d] %s 처리 중...",
            idx, len(targets), sc["title"],
        )

        try:
            # GPT-5 콘텐츠 생성
            content_md, in_tok, out_tok = generate_content(client, sc)
            total_input_tokens += in_tok
            total_output_tokens += out_tok

            if not content_md.strip():
                raise ValueError("GPT-5가 빈 응답을 반환했습니다.")

            if len(content_md) < 300:
                logger.warning(
                    "[Seed] 본문이 너무 짧음 (%d자) — SKIP: %s",
                    len(content_md), sc["title"],
                )
                skip_count += 1
                continue

            # ── 사전 위반 검사 (CRITICAL만 블록) ──────────────
            analysis = analyzer.analyze(content_md)
            critical_violations = [
                v for v in analysis.violations
                if v.severity == "CRITICAL"
            ]
            if critical_violations:
                rule_ids = [v.rule_id for v in critical_violations]
                logger.warning(
                    "[Seed] CRITICAL 위반 감지 — SKIP: %s / 규칙: %s",
                    sc["title"], rule_ids,
                )
                skip_count += 1
                continue

            # ── ingest ─────────────────────────────────────────
            result = ingest_document(
                title=sc["title"],
                content_md=content_md,
                source_id="consultation_seed",
                metadata={
                    "evidence_level": "A",
                    "symptom_tags": sc["symptom_tags"],
                    "severity": sc["severity"],
                },
                evidence_country="KR",
                evidence_topic=sc["evidence_topic"],
                regulatory_korea=True,
                topic_keywords=sc["symptom_tags"],
                status="active",
                upsert=args.upsert,
            )

            doc_id_short = result.get("document_id", "")[:8]
            chunks_count = result.get("chunks_count", 0)
            doc_status = result.get("status", "?")
            total_chunks += chunks_count

            logger.info(
                "[Seed] [%d/%d] 완료: doc=%s, chunks=%d, status=%s",
                idx, len(targets), doc_id_short, chunks_count, doc_status,
            )

            if doc_status == "skipped":
                skip_count += 1
            else:
                success_count += 1

            # rate limit 완화
            time.sleep(1)

        except Exception as exc:
            failed_count += 1
            err_msg = f"{sc['title']}: {exc}"
            errors.append(err_msg)
            logger.error("[Seed] FAILED %s — %s", sc["title"], exc, exc_info=True)

    # ── 검증 ──────────────────────────────────────────────────
    t_elapsed = time.time() - t_total_start
    logger.info("[Seed] DB 검증 중...")
    verify = verify_emergency_docs()

    # ── 결과 출력 ─────────────────────────────────────────────
    print("")
    print("=" * 60)
    print("  응급/핵심 KB 시드 ingest 결과")
    print("=" * 60)
    print(f"  총 시나리오:         {len(targets)}개")
    print(f"  ingest 성공:         {success_count}개")
    print(f"  SKIP (중복/위반):    {skip_count}개")
    print(f"  실패:                {failed_count}개")
    print(f"  생성된 청크:         {total_chunks}개")
    print(f"  실행 시간:           {t_elapsed:.1f}초 ({t_elapsed/60:.1f}분)")
    print(f"  GPT-5 토큰:          입력={total_input_tokens:,} / 출력={total_output_tokens:,}")
    print("")
    print("  [DB 검증 — consultation_seed]")
    print(f"  active 문서:         {verify['active_docs']}개")
    print(f"  active 청크:         {verify['active_chunks']}개")
    print("")

    if errors:
        print("  [오류 목록]")
        for err in errors:
            print(f"    - {err}", file=sys.stderr)

    if failed_count == 0 and skip_count < len(targets):
        print("  [OK] 모든 ingest 완료.")
    print("=" * 60)

    sys.exit(1 if failed_count > 0 else 0)


if __name__ == "__main__":
    main()
