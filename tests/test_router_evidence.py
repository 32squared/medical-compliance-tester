"""retrieval_router + evidence_pack 단위 테스트 (스펙 §5.2/§6)."""

import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from retrieval_router import route, source_priority_for, SOURCE_PRIORITY
from evidence_pack import build_evidence_pack, render_evidence_for_prompt


# ── Retrieval Router ─────────────────────────────────────────────────────────

def test_drug_routes_dur_first():
    r = route({"intent": "drug_safety", "retrieval_routes": []})
    assert "MFDS_DUR" in r["primary_sources"]
    assert r["allow_papers"] is False
    # DUR(rank1)이 PubMed(rank6)보다 앞
    assert r["ranked_routes"][0] in ("MFDS_DUR", "HIRA_DUR")


def test_infection_kdca_first():
    r = route({"intent": "infection"})
    assert r["ranked_routes"][0] == "KDCA"
    assert r["allow_papers"] is True


def test_emergency_safety_first():
    r = route({"intent": "emergency"})
    assert r["safety_first"] is True
    assert r["allow_papers"] is False


def test_crisis_retrieval_disabled():
    r = route({"intent": "mental_health_crisis"})
    assert r["safety_first"] is True
    assert r["retrieval_enabled"] is False


def test_explicit_routes_respected():
    r = route({"intent": "drug_safety", "retrieval_routes": ["HIRA_DUR", "MFDS_DUR"]})
    assert r["primary_sources"][0] == "HIRA_DUR"


def test_source_priority_mapping():
    assert source_priority_for("mfds") < source_priority_for("pubmed")
    assert source_priority_for("kdca") == SOURCE_PRIORITY["KDCA"]
    assert source_priority_for("unknown_xyz") == 6


# ── Evidence Pack ────────────────────────────────────────────────────────────

_CHUNKS = [
    {"chunk_id": "c1", "source_id": "pubmed", "content": "PubMed 논문 내용", "score": 0.9,
     "title": "paper", "jurisdiction": "US"},
    {"chunk_id": "c2", "source_id": "mfds", "content": "MFDS DUR 병용금기 정보", "score": 0.6,
     "title": "DUR", "jurisdiction": "KR"},
]


def test_evidence_pack_priority_orders_kr_first():
    pack = build_evidence_pack("이 약 같이 먹어도 돼?",
                               {"intent": "drug_safety", "risk_level": "high",
                                "population_tags": []}, _CHUNKS)
    # mfds(rank1)가 pubmed(rank6)보다 score 낮아도 E1으로 우선
    assert pack["evidence_items"][0]["source_id"] == "mfds"
    assert pack["evidence_items"][0]["evidence_id"] == "E1"


def test_evidence_pack_drug_limitation():
    pack = build_evidence_pack("임신 중 이부프로펜?",
                               {"intent": "drug_safety", "risk_level": "high",
                                "population_tags": ["pregnancy"]}, _CHUNKS)
    e_mfds = [e for e in pack["evidence_items"] if e["source_id"] == "mfds"][0]
    assert len(e_mfds["limitations"]) >= 1  # 약물/임신 → 한계 필수


def test_evidence_pack_conflict_detected():
    pack = build_evidence_pack("q", {"intent": "drug_safety", "risk_level": "high"}, _CHUNKS)
    assert pack["conflicts"], "국내+해외 혼재 시 충돌 메모 있어야"
    assert pack["conflicts"][0]["resolution_policy"] == "KR_official_source_first"


def test_evidence_pack_insufficient():
    pack = build_evidence_pack("q", {"intent": "symptom_info", "risk_level": "medium"}, [])
    assert pack["insufficient_evidence"] is True
    assert pack["classification"]["allowed_response_mode"] == "insufficient_information"


def test_answer_constraints_high_risk():
    pack = build_evidence_pack("q", {"intent": "drug_safety", "risk_level": "high"}, _CHUNKS)
    ac = pack["answer_constraints"]
    assert ac["must_cite_every_medical_claim"] is True
    assert ac["must_not_diagnose"] is True
    assert ac["must_include_clinician_consult_when_high_risk"] is True


def test_render_uses_E_markers():
    pack = build_evidence_pack("q", {"intent": "drug_safety", "risk_level": "high"}, _CHUNKS)
    txt = render_evidence_for_prompt(pack)
    assert "[E1]" in txt


if __name__ == "__main__":
    tests = [
        test_drug_routes_dur_first, test_infection_kdca_first, test_emergency_safety_first,
        test_crisis_retrieval_disabled, test_explicit_routes_respected, test_source_priority_mapping,
        test_evidence_pack_priority_orders_kr_first, test_evidence_pack_drug_limitation,
        test_evidence_pack_conflict_detected, test_evidence_pack_insufficient,
        test_answer_constraints_high_risk, test_render_uses_E_markers,
    ]
    passed = failed = 0
    for fn in tests:
        try:
            fn(); print(f"  PASS  {fn.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}"); failed += 1
        except Exception as e:
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}"); failed += 1
    print(f"\n결과: {passed}/{len(tests)} 통과")
    sys.exit(0 if failed == 0 else 1)
