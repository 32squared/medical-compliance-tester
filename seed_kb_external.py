"""
KB 시드 생성 스크립트 — External Phase (GPT-5 자동 생성 의학 정보)
====================================================================
GPT-5를 사용하여 한국 의료환경 기준 핵심 증상별 의학 정보를 자동 생성하고
KB에 status='pending_review'로 INSERT한다.

의료적 안전성:
  - 모든 자동 생성 문서는 status='pending_review'로만 저장
  - hybrid_search WHERE d.status='active' 조건으로 검색에서 자동 제외
  - 의사 reviewer가 kb_manager.html에서 명시적 승인 전까지 사용자 응답에 영향 없음

실행:
    python seed_kb_external.py
    python seed_kb_external.py --dry-run     # GPT 호출 없이 프롬프트만 출력
    python seed_kb_external.py --upsert      # 이미 존재하는 문서 덮어쓰기

Cloud Run Job 환경에서는 DATABASE_URL, OPENAI_API_KEY 환경변수가 필수.
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
_GPT_SOURCE = {
    "id": "gpt_generated_v1",
    "name": "GPT-5 자동 생성 의학 정보 (의사 검수 필요)",
    "source_type": "guideline",
    "license": "proprietary_internal",
    "update_frequency": "on_demand",
    "is_active": 1,
}

# ────────────────────────────────────────────
#  20개 핵심 증상 목록
# ────────────────────────────────────────────
#  (symptom_key, symptom_korean)
SYMPTOMS = [
    ("fever",            "발열"),
    ("headache",         "두통"),
    ("chest_pain",       "흉통"),
    ("abdominal_pain",   "복통"),
    ("cough",            "기침"),
    ("dyspnea",          "호흡곤란"),
    ("dizziness",        "어지럼"),
    ("fatigue",          "만성피로"),
    ("diarrhea",         "설사"),
    ("menstrual",        "생리이상"),
    ("chest_pain_resp",  "흉부불편감"),
    ("dysuria",          "배뇨통"),
    ("frequency",        "빈뇨"),
    ("hematuria",        "혈뇨"),
    ("numbness",         "손발저림"),
    ("palpitation",      "두근거림"),
    ("rash",             "발진"),
    ("itching",          "가려움"),
    ("myalgia",          "관절통"),
    ("trauma",           "외상"),
]

# ────────────────────────────────────────────
#  증상 → 진료과 매핑 (seed_kb_phase1.py 참조)
# ────────────────────────────────────────────
_DEPT_MAP = {
    "fever":           "내과",
    "headache":        "신경과",
    "chest_pain":      "순환기내과",
    "abdominal_pain":  "내과",
    "cough":           "내과",
    "dyspnea":         "내과",
    "dizziness":       "신경과",
    "fatigue":         "내과",
    "diarrhea":        "내과",
    "menstrual":       "산부인과",
    "chest_pain_resp": "내과",
    "dysuria":         "비뇨기과",
    "frequency":       "비뇨기과",
    "hematuria":       "비뇨기과",
    "numbness":        "신경과",
    "palpitation":     "순환기내과",
    "rash":            "피부과",
    "itching":         "피부과",
    "myalgia":         "정형외과",
    "trauma":          "응급의학과",
}

# ────────────────────────────────────────────
#  GPT 프롬프트 템플릿
# ────────────────────────────────────────────
_SYSTEM_PROMPT = (
    "당신은 한국 의료환경에서 활동하는 임상의입니다. "
    "요청된 증상에 대해 일반 의학 정보를 한국어 마크다운으로 작성하십시오. "
    "이 콘텐츠는 의사가 검수하기 전까지 환자에게 제공되지 않습니다."
)

_USER_PROMPT_TEMPLATE = """\
다음 증상에 대해 일반 의학 정보를 한국어 마크다운으로 작성하시오.

증상: {symptom_korean} ({symptom_key})

다음 4개 섹션으로 작성할 것:
## 일반적 원인
## 한국 의료환경에서의 초기 평가 (KMLE/대한의학회 일반 권고 수준)
## 응급 위험 신호 (Red Flags) — 119/응급실 권유 기준
## 자가 관리 가능 범위 및 진료과 안내

요구사항:
- 한국 의학 교과서(Harrison's, 대한의학회 권고안 등) 수준의 일반 사실만 작성
- 특정 환자에 대한 진단·처방 지시 금지
- 분량: 800-1500자
- 한국어로만 작성
- 출처 인용 금지 (이 콘텐츠 자체가 의료진 검수 대상)
- 의료법 준수: 병명 단정·처방·검사 지시 금지
"""


# ════════════════════════════════════════════
#  GPT-5 콘텐츠 생성 (비스트리밍)
# ════════════════════════════════════════════

def generate_content(client, symptom_key: str, symptom_ko: str) -> tuple:
    """
    GPT-5로 증상별 의학 정보 마크다운을 생성한다.

    Args:
        client:       openai.OpenAI 클라이언트 인스턴스
        symptom_key:  증상 영문 키 (예: 'fever')
        symptom_ko:   증상 한국어명 (예: '발열')

    Returns:
        (content_md: str, input_tokens: int, output_tokens: int)
    """
    user_prompt = _USER_PROMPT_TEMPLATE.format(
        symptom_korean=symptom_ko,
        symptom_key=symptom_key,
    )

    logger.info("[GenContent] GPT-5 호출: %s (%s)", symptom_ko, symptom_key)
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
        input_tokens = response.usage.prompt_tokens or 0
        output_tokens = response.usage.completion_tokens or 0

    elapsed = time.time() - t_start
    logger.info(
        "[GenContent] 완료: %s — %d자, token(in=%d, out=%d), %.1f초",
        symptom_ko, len(content_md), input_tokens, output_tokens, elapsed,
    )

    return content_md, input_tokens, output_tokens


# ════════════════════════════════════════════
#  source INSERT (멱등)
# ════════════════════════════════════════════

def seed_external_source() -> bool:
    """
    gpt_generated_v1 source를 kb_sources에 등록.
    이미 존재하면 SKIP.

    Returns:
        True if newly inserted, False if skipped.
    """
    from kb_ingest import seed_kb_sources

    inserted = seed_kb_sources([_GPT_SOURCE])
    if inserted > 0:
        logger.info("[Seed] source 등록 완료: %s", _GPT_SOURCE["id"])
        return True
    else:
        logger.info("[Seed] source 이미 존재 (SKIP): %s", _GPT_SOURCE["id"])
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


def verify_pending_docs() -> dict:
    """gpt_generated_v1 소스의 pending_review 문서/청크 수 검증."""
    from db import get_conn

    with get_conn() as (conn, cur):
        cur.execute(
            "SELECT COUNT(*) FROM kb_documents "
            "WHERE source_id = 'gpt_generated_v1' AND status = 'pending_review'"
        )
        pending_docs = _row_val(cur.fetchone())

        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks c "
            "JOIN kb_documents d ON c.document_id = d.id "
            "WHERE d.source_id = 'gpt_generated_v1' AND d.status = 'pending_review'"
        )
        pending_chunks = _row_val(cur.fetchone())

        cur.execute(
            "SELECT COUNT(*) FROM kb_chunks c "
            "JOIN kb_documents d ON c.document_id = d.id "
            "WHERE d.status = 'active'"
        )
        active_chunks = _row_val(cur.fetchone())

        cur.execute(
            "SELECT COUNT(*) FROM kb_documents WHERE status = 'active'"
        )
        active_docs = _row_val(cur.fetchone())

    return {
        "pending_docs":   pending_docs,
        "pending_chunks": pending_chunks,
        "active_docs":    active_docs,
        "active_chunks":  active_chunks,
    }


# ════════════════════════════════════════════
#  메인
# ════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "KB External Seed: GPT-5로 증상별 의학 정보 생성 → "
            "status='pending_review'로 INSERT (의사 검수 대기)"
        )
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="GPT 호출 없이 프롬프트만 출력, DB 저장 생략",
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
        metavar="SYMPTOM_KEY",
        help="특정 증상만 처리 (예: --only fever)",
    )
    args = parser.parse_args()

    # ── dry-run: 프롬프트 미리보기만 ──────────────────────────
    if args.dry_run:
        logger.info("[DryRun] GPT 호출 없이 프롬프트만 출력합니다.")
        targets = [
            (k, ko) for k, ko in SYMPTOMS
            if args.only is None or k == args.only
        ]
        for symptom_key, symptom_ko in targets[:3]:
            print("=" * 60)
            print(f"SYMPTOM: {symptom_ko} ({symptom_key})")
            print("-" * 40)
            print("[SYSTEM]", _SYSTEM_PROMPT)
            print("[USER]")
            print(_USER_PROMPT_TEMPLATE.format(
                symptom_korean=symptom_ko,
                symptom_key=symptom_key,
            ))
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

    logger.info("[Seed] DB 초기화...")
    init_db()

    # ── source 등록 ───────────────────────────────────────────
    logger.info("[Seed] gpt_generated_v1 source 등록 중...")
    seed_external_source()

    # ── OpenAI 클라이언트 초기화 ─────────────────────────────
    client = OpenAI(api_key=openai_key)

    # ── 처리 대상 필터링 ──────────────────────────────────────
    targets = [
        (k, ko) for k, ko in SYMPTOMS
        if args.only is None or k == args.only
    ]
    logger.info("[Seed] 처리 대상 증상: %d개", len(targets))

    # ── 통계 집계 변수 ────────────────────────────────────────
    t_total_start = time.time()
    total_input_tokens = 0
    total_output_tokens = 0
    success_count = 0
    skip_count = 0
    failed_count = 0
    total_chunks = 0
    errors = []

    # ── 증상별 순차 처리 ─────────────────────────────────────
    for idx, (symptom_key, symptom_ko) in enumerate(targets, 1):
        logger.info(
            "[Seed] [%d/%d] %s (%s) 처리 중...",
            idx, len(targets), symptom_ko, symptom_key,
        )

        department = _DEPT_MAP.get(symptom_key, "내과")

        # 제목: 검수 상태를 명시하여 UI에서 즉시 식별 가능
        title = f"{symptom_ko} 일반 의학 정보 (자동 생성, 검수 대기)"

        try:
            # GPT-5 콘텐츠 생성
            content_md, in_tok, out_tok = generate_content(
                client, symptom_key, symptom_ko
            )
            total_input_tokens += in_tok
            total_output_tokens += out_tok

            if not content_md.strip():
                raise ValueError("GPT-5가 빈 응답을 반환했습니다.")

            # 출처 고지 푸터 추가 (마크다운 문서 하단에 삽입)
            notice = (
                "\n\n---\n"
                "> **출처**: GPT-5 자동 생성 (한국 의료환경 기준 일반 의학 정보, 의사 검수 필요)  \n"
                "> **주의**: 이 문서는 의사 검수 대기 상태입니다. "
                "검수 완료 전까지 사용자 응답에 사용되지 않습니다.  \n"
                "> **의료법 고지**: 본 내용은 일반 정보이며 진단·처방을 대신하지 않습니다."
            )
            content_md_with_notice = content_md.rstrip() + notice

            # ingest: status='pending_review' 명시 — active로 절대 저장 안 됨
            result = ingest_document(
                title=title,
                content_md=content_md_with_notice,
                source_id="gpt_generated_v1",
                metadata={
                    "symptom_tags":  [symptom_key],
                    "department":    department,
                    "severity":      "moderate",
                    "auto_generated": True,
                    "review_required": True,
                    "generator":     "gpt-5",
                },
                evidence_country="KR",
                evidence_topic=symptom_key,
                regulatory_korea=False,
                topic_keywords=[symptom_ko, symptom_key, department],
                upsert=args.upsert,
                status="pending_review",   # 핵심: 검수 전 검색 제외
            )

            doc_status = result.get("status", "")
            if doc_status == "skipped":
                logger.info("[Seed] SKIP (이미 존재): %s", title)
                skip_count += 1
            else:
                chunks_created = result.get("chunks_count", 0)
                total_chunks += chunks_created
                success_count += 1
                logger.info(
                    "[Seed] 저장 완료: %s — %d 청크 (status=pending_review)",
                    title, chunks_created,
                )

        except Exception as exc:
            failed_count += 1
            err_msg = f"{symptom_ko} ({symptom_key}): {exc}"
            errors.append(err_msg)
            logger.error("[Seed] FAILED: %s", err_msg)

        # GPT-5 rate limit 완화 — 연속 호출 사이 간격
        if idx < len(targets):
            time.sleep(1.0)

    t_elapsed = time.time() - t_total_start

    # ── DB 검증 ───────────────────────────────────────────────
    logger.info("[Seed] DB 검증 중...")
    verify = verify_pending_docs()

    # ── 비용 추정 (GPT-5 기준: input $15/1M, output $60/1M) ──
    cost_input  = total_input_tokens  / 1_000_000 * 15.0
    cost_output = total_output_tokens / 1_000_000 * 60.0
    cost_total  = cost_input + cost_output

    # ── 결과 출력 ─────────────────────────────────────────────
    print("")
    print("=" * 60)
    print("  외부 의학 근거 KB 시드 결과")
    print("=" * 60)
    print(f"  대상 증상:              {len(targets)}개")
    print(f"  생성 성공:              {success_count}개")
    print(f"  SKIP (이미 존재):       {skip_count}개")
    print(f"  실패:                   {failed_count}개")
    print(f"  생성된 청크:            {total_chunks}개 (검색에서 자동 제외)")
    print(f"  실행 시간:              {t_elapsed:.1f}초 ({t_elapsed / 60:.1f}분)")
    print("")
    print("  [GPT-5 토큰 사용]")
    print(f"  input  tokens:          {total_input_tokens:,}")
    print(f"  output tokens:          {total_output_tokens:,}")
    print(f"  비용 추정:              ${cost_total:.4f} "
          f"(input ${cost_input:.4f} + output ${cost_output:.4f})")
    print("")
    print("  [DB 검증 — pending_review 안전성 확인]")
    print(f"  pending 문서:           {verify['pending_docs']}개")
    print(f"  pending 청크:           {verify['pending_chunks']}개")
    print(f"  active 문서:            {verify['active_docs']}개 (변동 없어야 함)")
    print(f"  active 청크:            {verify['active_chunks']}개 (변동 없어야 함)")
    print("")

    # 안전성 검증 — active가 늘었으면 즉각 경고
    if verify["pending_docs"] != success_count + skip_count:
        print(
            f"  [WARN] pending_docs({verify['pending_docs']}) != "
            f"success+skip({success_count + skip_count}). 확인 필요."
        )

    if errors:
        print("  [ERRORS]")
        for err in errors:
            print(f"    - {err}", file=sys.stderr)

    print("")
    print("  [다음 단계 — 의사 액션 필요]")
    print("  kb_manager.html > 'pending_review' 필터 > 각 문서 검토 후 '활성화' 또는 '거부'")
    print("  검토 완료된 문서만 검색에 노출됩니다.")
    print("=" * 60)

    sys.exit(1 if failed_count > 0 else 0)


if __name__ == "__main__":
    main()
