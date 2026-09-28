# -*- coding: utf-8 -*-
"""eval_v3.run_summary / verdict_of — 온톨로지 평가 페이지의 실행별 집계(LLM·서브모듈 불필요)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import eval_v3  # noqa: E402


def _r(sid, cat, v3, final_source='v3'):
    return {"scenarioId": sid, "category": cat, "finalSource": final_source, "evalV3": v3}


def test_verdict_of():
    assert eval_v3.verdict_of(None) is None
    assert eval_v3.verdict_of({"error": "x"}) is None
    assert eval_v3.verdict_of({"legal_verdict": "fail", "validity_grade": "A"}) == "FAIL"
    assert eval_v3.verdict_of({"legal_verdict": "pass", "validity_grade": "b"}) == "B"
    assert eval_v3.verdict_of({"legal_verdict": "pass"}) == "PASS"


def test_run_summary_none_without_v3():
    assert eval_v3.run_summary([]) is None
    assert eval_v3.run_summary([{"scenarioId": "S1", "gptEval": {"grade": "A"}}]) is None


def test_run_summary_counts():
    results = [
        _r("S1", "진단", {"legal_verdict": "pass", "validity_axis": "PV", "validity_grade": "A",
                         "uv_grade": "C", "uv_unmet": ["UV-01", "UV-02"], "uv_intent": "test_options",
                         "rag_meta": {"prompt_version": "v18"}, "judge_model": "gpt-5.4-mini",
                         "ontology_version": "v3.5", "eval_version": "v3.0-dev"}),
        _r("S2", "진단", {"legal_verdict": "fail", "legal_hits": ["LG-02"], "legal_review_hits": ["LG-11"],
                         "validity_axis": "SV", "validity_grade": "C", "validity_unmet": ["SV-02"],
                         "prompt_version": "v18", "judge_model": "gpt-5.4",
                         "judge_escalation": {"first_model": "gpt-5.4-mini", "first_verdict": "FAIL",
                                              "model": "gpt-5.4", "verdict": "FAIL"}}),
        _r("S3", "자문", {"legal_verdict": "pass", "validity_axis": "PV", "validity_grade": "B",
                         "validity_unmet": ["PV-04"], "prompt_version": "v17",
                         "judge_escalation": {"first_model": "gpt-5.4-mini", "first_verdict": "FAIL",
                                              "model": "gpt-5.4", "verdict": "B"}}, final_source='rubric'),
        _r("S4", "자문", {"error": "boom"}),
        {"scenarioId": "S5", "category": "자문"},          # v3 없음 — 세지 않는다
    ]
    s = eval_v3.run_summary(results)
    assert s["n"] == 4 and s["err"] == 1
    assert s["gate"] == {"pass": 2, "fail": 1, "review": 0}
    assert s["verdict"] == {"A": 1, "FAIL": 1, "B": 1}
    assert s["validity"] == {"A": 1, "C": 1, "B": 1}
    assert s["uv"] == {"C": 1, "-": 2}
    assert s["axis"] == {"PV": 2, "SV": 1}
    assert s["rule_hits"] == {"LG-02": 1} and s["review_hits"] == {"LG-11": 1}
    assert s["unmet"] == {"SV-02": 1, "PV-04": 1} and s["uv_unmet"] == {"UV-01": 1, "UV-02": 1}
    assert s["prompt_versions"] == {"v18": 2, "v17": 1}
    assert s["escalated"] == 2 and s["escalated_fail"] == 1
    assert s["final_v3"] == 3
    assert s["judge_model"] == "gpt-5.4-mini" and s["escalate_model"] == "gpt-5.4"
    assert s["ontology_version"] == "v3.5" and s["eval_version"] == "v3.0-dev"
    assert s["categories"] == {"진단": {"n": 2, "fail": 1, "err": 0}, "자문": {"n": 2, "fail": 0, "err": 1}}
