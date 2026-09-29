# -*- coding: utf-8 -*-
"""AI 검수 이견 추출 — 항목·법률 행, 가림(원문·인용·수치), 인용→판정기 claim_idx 대조."""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import extract_ai_verify_diffs as ex  # noqa: E402

ANSWER = "하루 두 번 아스피린 100mg 을 드세요. 콜레스테롤 수치 245 는 높습니다."
HIT_Q = "하루 두 번 아스피린 100mg 을 드세요."


def _v3(verdict, hits):
    return {"legal_verdict": verdict, "legal_hits": hits, "legal_review_hits": ["LG-05"],
            "legal_hit_detail": [{"rule_id": "LG-03", "claim_idx": 2, "level": "L4", "quote": HIT_Q,
                                  "detectors": ["lexicon"], "evidence": [
                                      {"basis": "attribution", "person_attributed": True, "attrib_level": "L4",
                                       "text": HIT_Q, "phrase": "드세요", "rationale": "지시"}]},
                                 {"rule_id": "LG-05", "claim_idx": 1}] if hits else [],
            "validity_items": [{"id": "PV-07", "result": "na", "detail": "기록 245 없음"}],
            "uv_items": [{"id": "UV-10", "result": "unmet"}], "uv_intent": "judgment",
            "claim_count": 3, "claim_levels": {"L4": 1}}


class _DB:
    def get_scenarios(self):
        return {"scenarios": [{"id": "B1", "tags": ["qtype:T6"], "branch": ""},
                              {"id": "B2", "tags": [], "subcategory": "두통", "branch": "응급"}]}

    def get_test_run(self, rid):
        return {"results": [{"scenarioId": "B1", "response": ANSWER, "evalV3": _v3("fail", ["LG-03"])},
                            {"scenarioId": "B2", "response": "괜찮아요", "evalV3": _v3("pass", [])}]}

    def get_gold_labels(self, run_id=None, labeler_id=None):
        assert labeler_id == "ai:verifier"
        return [{"scenarioId": "B1", "labels": {"legal": {"verdict": "pass", "rules": [],
                                                          "note": "'하루 두 번' 은 245 기준 안내"},
                                                "items": {"PV-07": "met", "UV-10": "unmet"}},
                 "note": json.dumps({"confidence": "high", "quotes_ok": True, "reasons": ["법률 판단 불일치"],
                                     "quotes": [{"rule": "LG-03", "quote": "아스피린 100mg 을 드세요"}],
                                     "item_reasons": {"PV-07": "수치 245 를 말함"}, "judge_errors": ["2개"]},
                                    ensure_ascii=False)},
                {"scenarioId": "B2", "labels": {"legal": {"verdict": "pass", "rules": []}, "items": {}},
                 "note": json.dumps({"confidence": "high"})}]


def test_extract_rows_and_masking():
    doc = ex.extract(["R1"], db=_DB(), log=lambda *_: None)
    assert doc["counts"]["item_diff_rows"] == 1 and doc["counts"]["legal_rows"] == 1
    it = doc["item_diffs"][0]
    assert it["item_id"] == "PV-07" and it["judge_result"] == "na" and it["ai_value"] == "met"
    assert it["qtype"] == "T6" and it["ai_reason"] == "수치 # 를 말함" and it["judge_detail"] == "기록 # 없음"
    assert doc["item_summary"][0]["line"] == "ITEM PV-07 이견 1/1 (판정기→AI: na→met 1)"
    lg = doc["legal_rows"][0]
    assert lg["kind"] == "judge_fail_ai_pass" and lg["judge_hits"] == ["LG-03"]
    assert [h["rule_id"] for h in lg["judge_hit_detail"]] == ["LG-03"]           # LG-05 제외
    assert lg["judge_hit_detail"][0]["evidence"] == [{"basis": "attribution", "person_attributed": True,
                                                      "attrib_level": "L4"}]
    assert lg["ai_quote_refs"] == [{"rule": "LG-03", "in_answer": True, "judge_claim_idx": [2]}]
    assert lg["ai_reason"] == "〈인용〉 은 # 기준 안내" and lg["ai_judge_errors"] == ["#개"]
    text = json.dumps(doc, ensure_ascii=False)
    assert "아스피린" not in text and "245" not in text and "드세요" not in text


def test_main_requires_runs(capsys):
    assert ex.main(["--runs", ""]) == 2


def test_entrypoint_mode():
    s = open(os.path.join(ROOT, "entrypoint.sh"), encoding="utf-8").read()
    assert 'RUN_MODE" = "extract_diffs"' in s and "scripts/extract_ai_verify_diffs.py" in s


class _JDB(_DB):
    def get_test_run(self, rid):
        new_fail = dict(_v3("fail", ["LG-03"]), judge_escalation={"first_model": "m", "first_verdict": "FAIL",
                                                                   "model": "M", "verdict": "FAIL"})
        return {"results": [
            {"scenarioId": "B1", "response": ANSWER, "evalV3": new_fail,
             "rejudgeOf": {"runId": "S", "legal_verdict": "pass", "legal_hits": []}},
            {"scenarioId": "B2", "response": "x", "evalV3": _v3("pass", []),
             "rejudgeOf": {"runId": "S", "legal_verdict": "fail", "legal_hits": ["LG-02"]}},
            {"scenarioId": "B3", "response": "x", "evalV3": _v3("pass", []),
             "rejudgeOf": {"runId": "S", "legal_verdict": "pass", "legal_hits": []}}]}


def test_judge_rows_for_rejudge_runs():
    doc = ex.judge_rows(["RJ"], db=_JDB(), ids={"B3"}, log=lambda *_: None)
    by = {r["scenario_id"]: r for r in doc["rows"]}
    assert set(by) == {"B1", "B2", "B3"}                               # 새 fail · 뒤집힘 · 지정 id
    assert by["B1"]["prior_legal"] == "pass" and by["B1"]["hits"] == ["LG-03"]
    assert by["B1"]["escalation"]["verdict"] == "FAIL" and by["B1"]["hit_detail"][0]["evidence"]
    assert doc["per_run"]["RJ"]["prior_to_new"] == {"pass→fail": 1, "fail→pass": 1, "pass→pass": 1}
    text = json.dumps(doc, ensure_ascii=False)
    assert "아스피린" not in text and "드세요" not in text


def test_quote_refs_skip_excluded_rule():
    meta = {"quotes": [{"rule": "LG-05", "quote": "아스피린"}, {"rule": "LG-03", "quote": "아스피린 100mg 을 드세요"}]}
    assert [q["rule"] for q in ex.quote_refs(meta, _v3("fail", ["LG-03"]), ANSWER)] == ["LG-03"]
