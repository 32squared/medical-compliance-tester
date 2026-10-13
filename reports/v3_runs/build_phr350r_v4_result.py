# -*- coding: utf-8 -*-
"""REQ-VXKQ 회신 자료 하나로 묶기 — 판정 메타만(답변 원문·인용·케이스 수치 없음).

    python build_phr350r_v4_result.py <scratch_dir> <out.json>
입력(scratch_dir): compare_v4.json(phr350r_v4_compare.py 결과) · judge_rows.json(extract_diffs JUDGE_RUNS) ·
  pharmacist.json(count_pharmacist_closings 출력) · [ai_diffs.json](extract_diffs DIFF_RUNS 결과, 있으면 요약)
"""
import json
import os
import sys
from collections import Counter

S, OUT = sys.argv[1], sys.argv[2]
cmp_ = json.load(open(f"{S}/compare_v4.json", encoding="utf-8"))
jr = json.load(open(f"{S}/judge_rows.json", encoding="utf-8"))
ph = json.load(open(f"{S}/pharmacist.json", encoding="utf-8"))
EV_KEYS = ("basis", "phrase_id", "kind", "status", "example_code", "same_as_nearest",
           "person_attributed", "attrib_source", "attrib_level")


def hit_rows(r):
    out = []
    for h in r.get("hit_detail") or []:
        out.append({"rule_id": h.get("rule_id"), "claim_idx": h.get("claim_idx"), "level": h.get("level"),
                    "status": h.get("status"), "review": h.get("review"), "detectors": h.get("detectors"),
                    "evidence": [{k: e[k] for k in EV_KEYS if k in e} for e in h.get("evidence") or []]})
    return out


rows = {}
for r in jr["rows"]:
    rows.setdefault(r["scenario_id"], {})[r["run_id"]] = {
        "qtype": r.get("qtype"), "legal": r["legal"], "hits": r["hits"], "review_hits": r["review_hits"],
        "escalation": r.get("escalation"), "claim_count": r.get("claim_count"), "claim_levels": r.get("claim_levels"),
        "hit_detail": hit_rows(r)}

doc = {
    "request": "REQ-VXKQ",
    "generated": "2026-10-13",
    "runs": {
        "C_before": {"run_id": "phr350r-v3-20260930-1111", "judge": "v3.1 · ontology v3.8 · legal(버전 필드 없음) · uv-v6",
                     "answers": "운영 SKIX v18, 2026-09-30"},
        "D_after": {"run_id": "phr350r-v4rj-20261013-0754", "judge": "v3.1 · ontology v3.18 · legal-v7 · pv-v3 · sv-v2 · uv-v13 (서브모듈 55e8865)",
                    "answers": "운영 SKIX v18, 2026-10-12 (run phr350r-v4-20261012-0422 의 답변 350건을 rejudge_v3 로 판정)",
                    "note": "0422 실행 자체의 판정은 OpenAI 잔액 0 구간이라 전부 fallback — 무효. 10/13 잔액 복구 뒤 같은 답변을 다시 판정한 것이 D."},
        "settings": "EVAL_V3=1 · gpt-5.4-mini 1차 → 법률 fail 만 gpt-5.4 2차 · EVAL_PHR=0 · EVAL_V2_LEGAL=0 · EVAL_FINAL=v3 · SKIX_ENV=prod · 문항 세트 phr_case_r 350 (PHRQR-B####, T3 금지 문구 개정본)",
    },
    "n": cmp_["n"],
    "axes": {k: {"legal": cmp_[k]["legal"], "rule_hits": cmp_[k]["rule_hits"], "review_hits": cmp_[k]["review_hits"],
                 "pv": cmp_[k]["pv"], "pv_unmet": cmp_[k]["pv_unmet"], "uv": cmp_[k]["uv"], "uv_unmet": cmp_[k]["uv_unmet"],
                 "all_A": cmp_[k]["all_A"], "escalated": cmp_[k]["escalated"], "fallback_items": cmp_[k]["fallback_items"],
                 "claims_avg": cmp_[k]["claims_avg"], "len_avg": cmp_[k]["len_avg"], "intent": cmp_[k]["intent"],
                 "T3": cmp_[k]["T3"], "by_qtype": cmp_[k]["by_qtype"]} for k in ("C", "D")},
    "transitions_C_to_D": cmp_["C→D"],
    "legal_fail_hits_D": {sid: rows[sid]["phr350r-v4rj-20261013-0754"] for sid in sorted(cmp_["D"]["legal_fail"])
                          if sid in rows and "phr350r-v4rj-20261013-0754" in rows[sid]},
    "legal_fail_hits_C": {sid: rows[sid]["phr350r-v3-20260930-1111"] for sid in sorted(cmp_["C"]["legal_fail"])
                          if sid in rows and "phr350r-v3-20260930-1111" in rows[sid]},
    "REQ-0013_scope_before_after": cmp_["REQ-0013"],
    "pharmacist_only_closing": {rid: {k: v for k, v in d.items() if not k.startswith("ids_")} for rid, d in ph.items()},
    "notes": [
        "답변 원문·판정기 quote·evidence text/phrase/rationale·케이스 수치 제외. id·건수·규칙 id·phrase_id 만.",
        "PV 는 v3.1 부터 grade=null 이라 grade_legacy 로 이어 쓴 등급(validity_grade_source=legacy).",
        "REQ-0013 범위의 general100 id(DIAG-097·전신·피-008·EMER-090·EMER-102·PRES-110·EMER-069)는 이 문항 세트에 없어 전후가 없다.",
    ],
}
ai = f"{S}/ai_diffs.json"
if os.path.exists(ai):
    a = json.load(open(ai, encoding="utf-8"))
    summ = {"runs": a.get("runs"), "per_run": a.get("per_run"), "counts": a.get("counts")}
    for k in ("item_summary", "legal_summary", "ITEM", "legal_counts"):
        if k in a:
            summ[k] = a[k]
    items = a.get("item_diffs") or []
    if items:
        summ["item_diffs_by_item"] = dict(Counter(
            f"{x.get('item_id')}:{x.get('judge_result')}→{x.get('ai_value')}" for x in items).most_common(40))
        summ["item_diffs_rows"] = len(items)
        summ["item_diffs_by_qtype"] = dict(Counter(x.get("qtype") or "?" for x in items))
    legal = a.get("legal_rows") or []
    if legal:
        summ["legal_rows"] = len(legal)
        summ["legal_rows_by_kind"] = dict(Counter(x.get("kind") or x.get("category") or "?" for x in legal))
        summ["legal_rows_ids"] = [{"scenario_id": x.get("scenario_id"), "kind": x.get("kind"), "judge_hits": x.get("judge_hits"),
                                   "ai_rules": x.get("ai_rules"), "needs_human": x.get("needs_human")} for x in legal]
    doc["ai_verify_diffs_rejudge_v318"] = summ
json.dump(doc, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("wrote", OUT, "keys", list(doc))
