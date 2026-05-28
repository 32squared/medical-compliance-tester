"""
RAG 모듈 직접 호출 검증 — 인증 없이 백엔드 로직만 검증.
운영 DB 연결 (DATABASE_URL 또는 DB_PASSWORD 등 환경변수 필요).
Cloud Run Job 안에서 실행.

generate_response() 시그니처:
    generate_response(query: str, conversation_id: str,
                      provider_id: str = None, top_k: int = 5,
                      enable_guardrails: bool = True) -> Iterator[Dict]

STOP 이벤트 필드: evidence_quality, gate_decision, rag_query_id, citations, latency_ms
EVIDENCE_CHECK 이벤트 필드: quality, decision, top1_score, chunk_count, reasons
INFO 이벤트 필드: data.search_results (청크 목록)
"""

import os
import sys
import json
import time
import logging
import uuid
from typing import Dict, List

# 프로젝트 루트 추가 (tests/ → 상위 디렉토리)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/..")

# rag_engine 직접 import — generate_response()를 HTTP 없이 호출
from rag_engine import generate_response

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("validate_rag_direct")

SCENARIOS = [
    {
        "id": 1,
        "q": "성인 심정지 시 어떻게 해야 하나요?",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["nemc"],
    },
    {
        "id": 2,
        "q": "갑상선 검사는 어떻게 진행되나요?",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["health_kdca"],
    },
    {
        "id": 3,
        "q": "당뇨병이란 무엇인가요?",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["health_kdca"],
    },
    {
        "id": 4,
        "q": "AED(자동심장충격기) 사용법 알려주세요",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["nemc"],
    },
    {
        "id": 5,
        "q": "기저귀피부염 어떻게 관리해야 하나요?",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["health_kdca"],
    },
    {
        "id": 6,
        "q": "발열 시 어떻게 해야 하나요?",
        "expect_quality": ["high", "medium", "low"],
        "expect_sources": ["consultation_seed", "nemc", "health_kdca"],
    },
    {
        "id": 7,
        "q": "응급실에 가야 하는 기준이 뭐예요?",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["nemc"],
    },
    {
        "id": 8,
        "q": "에볼라 바이러스 한국 치료 가이드라인",
        "expect_quality": ["low", "insufficient", "medium"],
        "expect_sources": [],
    },
    {
        "id": 9,
        "q": "화성 거주민이 받은 외계 약품의 부작용",
        "expect_quality": ["insufficient", "low"],
        "expect_sources": [],
    },
    {
        "id": 10,
        "q": "기침이 2주 넘게 지속되면 어떻게 해야 하나요?",
        "expect_quality": ["high", "medium"],
        "expect_sources": ["consultation_seed", "health_kdca"],
    },
]


def run_one(scenario: Dict) -> Dict:
    """
    generate_response() 제너레이터에서 이벤트를 수집하고 검증 결과를 반환.
    conversation_id는 시나리오별로 신규 UUID를 사용 (conversations 테이블에 없어도
    generate_response 내부에서 emergency_state SELECT 시 None을 반환하므로 안전).
    """
    # 신규 UUID — 운영 대화와 충돌 없이 독립적으로 rag_queries 행 INSERT됨
    conv_id = f"validate-{uuid.uuid4()}"

    events_by_type: Dict[str, list] = {}
    full_text = ""
    evidence_check = None
    stop_data = None
    citations: List[Dict] = []

    t_start = time.time()
    try:
        gen = generate_response(
            query=scenario["q"],
            conversation_id=conv_id,
            provider_id=None,
            top_k=5,
            enable_guardrails=True,
        )
        for event in gen:
            etype = event.get("type", "UNKNOWN")
            events_by_type.setdefault(etype, []).append(event)

            if etype == "EVIDENCE_CHECK":
                # data 키 아래에 필드들이 있음
                evidence_check = event.get("data", event)

            elif etype == "GENERATION":
                full_text += event.get("text", "")

            elif etype == "INFO":
                sr = (event.get("data") or {}).get("search_results", [])
                if sr:
                    citations.extend(sr)

            elif etype == "STOP":
                stop_data = event
                # STOP 이벤트에도 citations 포함될 수 있음
                if not citations:
                    citations = event.get("citations", []) or []

            elif etype == "ERROR":
                logger.error("시나리오 %s ERROR 이벤트: %s", scenario["id"], event.get("message"))

    except Exception as e:
        logger.exception("시나리오 %s 실행 중 예외 발생", scenario["id"])
        return {
            "id": scenario["id"],
            "q": scenario["q"][:40],
            "conv_id": conv_id,
            "verdict": "ERROR",
            "error": str(e),
        }

    latency_ms = int((time.time() - t_start) * 1000)

    # ── 결과 추출 ────────────────────────────────────────────────
    # evidence_quality: STOP 이벤트 우선, 없으면 EVIDENCE_CHECK에서 가져옴
    actual_quality = None
    if stop_data:
        actual_quality = stop_data.get("evidence_quality")
    if not actual_quality and evidence_check:
        actual_quality = evidence_check.get("quality")

    gate_decision = None
    if stop_data:
        gate_decision = stop_data.get("gate_decision")
    if not gate_decision and evidence_check:
        gate_decision = evidence_check.get("decision")

    top1_score = (evidence_check or {}).get("top1_score")

    # citations source_id 추출 — INFO 이벤트의 search_results 또는 STOP.citations
    actual_sources = list(set(
        c.get("source_id") for c in citations
        if c and c.get("source_id")
    ))

    # ── 통과 기준 ────────────────────────────────────────────────
    quality_pass = (actual_quality in scenario["expect_quality"]) if actual_quality else False
    sources_pass = (
        not scenario["expect_sources"]  # expect_sources=[] 이면 소스 검사 생략
        or any(s in scenario["expect_sources"] for s in actual_sources)
    )
    ec_present = evidence_check is not None
    stop_present = stop_data is not None

    verdict = "PASS" if (quality_pass and sources_pass and ec_present and stop_present) else "FAIL"

    return {
        "id": scenario["id"],
        "q": scenario["q"][:40],
        "conv_id": conv_id,
        "actual_quality": actual_quality,
        "expected_quality": scenario["expect_quality"],
        "quality_pass": quality_pass,
        "actual_sources": actual_sources,
        "expected_sources": scenario["expect_sources"],
        "sources_pass": sources_pass,
        "ec_present": ec_present,
        "stop_present": stop_present,
        "gate_decision": gate_decision,
        "top1_score": round(top1_score, 4) if isinstance(top1_score, float) else top1_score,
        "citations_count": len(citations),
        "text_length": len(full_text),
        "latency_ms": latency_ms,
        "verdict": verdict,
        "rag_query_id": (stop_data or {}).get("rag_query_id"),
        "guardrail_action": (stop_data or {}).get("guardrail_action"),
        "event_types": list(events_by_type.keys()),
    }


def main():
    print("\n" + "=" * 60)
    print("  RAG 모듈 직접 호출 검증 (Cloud Run Job)")
    print("  RETRIEVAL_GATE_ENFORCE:", os.environ.get("RETRIEVAL_GATE_ENFORCE", "false"))
    print("  GATE_TOP1_PASS:", os.environ.get("GATE_TOP1_PASS", "0.55"))
    print("=" * 60)

    results = []
    for s in SCENARIOS:
        print(f"\n[{s['id']:02d}/10] {s['q'][:50]}")
        r = run_one(s)
        results.append(r)
        print(
            f"  verdict={r.get('verdict')} | quality={r.get('actual_quality')} "
            f"| gate={r.get('gate_decision')} | top1={r.get('top1_score')} "
            f"| sources={r.get('actual_sources')} | latency={r.get('latency_ms')}ms"
        )
        # 시나리오 간 1초 대기 (rate-limit 방어)
        time.sleep(1)

    # ── 집계 ─────────────────────────────────────────────────────
    pass_count = sum(1 for r in results if r.get("verdict") == "PASS")
    fail_count = sum(1 for r in results if r.get("verdict") == "FAIL")
    error_count = sum(1 for r in results if r.get("verdict") == "ERROR")
    ec_count = sum(1 for r in results if r.get("ec_present"))
    avg_latency = sum(r.get("latency_ms", 0) for r in results) / max(1, len(results))

    gate_pass_count = sum(1 for r in results if r.get("gate_decision") == "PASS")
    gate_weak_count = sum(1 for r in results if r.get("gate_decision") == "WEAK_PASS")
    gate_insuf_count = sum(1 for r in results if r.get("gate_decision") == "INSUFFICIENT")

    db_insert_count = sum(1 for r in results if r.get("rag_query_id"))

    top1_scores = [r["top1_score"] for r in results if isinstance(r.get("top1_score"), float)]
    avg_top1 = sum(top1_scores) / len(top1_scores) if top1_scores else None

    print("\n" + "=" * 60)
    print(f"  PASS {pass_count}/10 | FAIL {fail_count} | ERROR {error_count}")
    print(f"  EC 수신율: {ec_count}/10")
    print(f"  평균 latency: {avg_latency:.0f}ms")
    print(f"  shadow gate — PASS:{gate_pass_count} WEAK_PASS:{gate_weak_count} INSUFFICIENT:{gate_insuf_count}")
    print(f"  rag_queries INSERT: {db_insert_count}/10")
    print(f"  평균 top1_score: {avg_top1:.4f}" if avg_top1 is not None else "  평균 top1_score: N/A")
    print("=" * 60)

    # ── 시나리오별 상세 결과 (JSON) ───────────────────────────────
    print("\n[상세 결과]")
    for r in results:
        print(json.dumps(r, ensure_ascii=False, indent=2))

    # ── 최종 EXIT 코드 — ERROR 시 비정상 종료 (Job 실패 플래그) ──
    if error_count > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
