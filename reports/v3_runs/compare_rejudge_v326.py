"""10/16 DEV 1000건(PHR 350·일반 650) 재판정 — 판정기 v3.23(3ee56fb, 10/22) → v3.26(18153a9: legal-v11·uv-v15·pv-v5·fact-v9) 대조.

측정 표(docs/eval_v3/host_todo_eval_b8ac6c8_20261026.md 「한 run 에서 측정할 것」)대로 네 축을 만든다.
  (a) REQ-LQMP — 일반 650 법률 FAIL 수·구성, review 두 값(context_candidate_explanation·context_care_notice) 분포,
      「홀로 선 진료과 권고(LG-05 L6)」 FAIL 잔존 수
  (b) REQ-A2ZH — PHR 350 의 거짓 미충족 26건(21 문항, DOC-H6HQB) 해소 여부, 통과(met)→미충족(unmet) 역방향 전수
  (c) PR #59 — PV-04 전이(unmet→na·met→na·잔존 unmet 의 질문 의도), B0052·B0715·B0925 참고 등급(grade_legacy)
  (d) REQ-XDIA — 일반 650 SV 키워드 경로 met(감사 '타당' 항목 중 LLM 2차 없이 met) 불변 확인, SV 항목 결과 전수 대조
LG·UV·PV 축은 '판정기 판 변경' 이라 등급 분포는 참고로만 적고 섞어 비교하지 않는다.
PHR 원문·실제 검진 값은 출력하지 않는다(문항 id·항목 id·문장 번호·건수만).

사용:
  python compare_rejudge_v326.py --old-phr <v323 phr json> --old-gen <v323 gen json> \
      --new-phr <v326 phr json> --new-gen <v326 gen json> \
      --verdicts-dir reports/v3_runs/cd_audit_20261019 --out-json <json> --out-md <md>
"""
import argparse
import glob
import json
import os
import sys
from collections import Counter, defaultdict

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

GRADES = ("A", "B", "C", "D")
RUN_LABELS = {"phr": "PHR 350", "gen": "일반 650"}
REVIEW_NEW = ("context_candidate_explanation", "context_care_notice")

# REQ-A2ZH 거짓 미충족 26건(21 문항) — DOC-H6HQB(sentences_req_a2zh_20261020.md) 머리말 그대로
A2ZH_ITEMS = {
    "PHRQR-B0005": ["PV-01"], "PHRQR-B0036": ["UV-01"], "PHRQR-B0052": ["PV-03"],
    "PHRQR-B0132": ["UV-01", "UV-02"], "PHRQR-B0136": ["UV-01", "UV-04", "UV-02"],
    "PHRQR-B0153": ["UV-01", "UV-02"], "PHRQR-B0325": ["UV-01"], "PHRQR-B0442": ["UV-02"],
    "PHRQR-B0446": ["UV-01"], "PHRQR-B0502": ["UV-04"], "PHRQR-B0527": ["UV-01"],
    "PHRQR-B0588": ["UV-04"], "PHRQR-B0715": ["PV-03"], "PHRQR-B0744": ["UV-04"],
    "PHRQR-B0824": ["UV-01"], "PHRQR-B0833": ["UV-04", "UV-02"], "PHRQR-B0925": ["PV-03"],
    "PHRQR-B0934": ["UV-01"], "PHRQR-B0978": ["UV-04"], "PHRQR-B1029": ["UV-01"], "PHRQR-B1291": ["UV-04"],
}
PV04_TARGETS = ("PHRQR-B0052", "PHRQR-B0715", "PHRQR-B0925")


def load(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = d["results_json"] if isinstance(d, dict) else d
    if isinstance(rows, str):
        rows = json.loads(rows)
    meta = {k: d.get(k) for k in ("id", "run_at", "total", "passed", "failed", "env", "status")} if isinstance(d, dict) else {}
    return meta, {r["scenarioId"]: r for r in rows if isinstance(r, dict) and r.get("scenarioId")}


def ev(r):
    e = (r or {}).get("evalV3") or {}
    return e if isinstance(e, dict) else {}


def items_by_id(e, key):
    return {i["id"]: i for i in (e.get(key) or []) if isinstance(i, dict) and i.get("id")}


def grade_dist(rows, key):
    c = Counter(str(ev(r).get(key) or "-") for r in rows.values())
    return {g: c.get(g, 0) for g in (*GRADES, "-")}


def dist(rows, key):
    return dict(Counter(str(ev(r).get(key) or "-") for r in rows.values()))


def moves(old, new, key):
    m = Counter()
    for sid, r in old.items():
        m[f"{str(ev(r).get(key) or '-')}→{str(ev(new.get(sid)).get(key) or '-')}"] += 1
    return dict(sorted(m.items(), key=lambda kv: (-kv[1], kv[0])))


def item_dist(rows, key):
    out = defaultdict(Counter)
    for r in rows.values():
        for i in ev(r).get(key) or []:
            if isinstance(i, dict) and i.get("id"):
                out[i["id"]][str(i.get("result"))] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def hit_details(e):
    return [h for h in (e.get("legal_hit_detail") or []) if isinstance(h, dict)]


def confirmed_rules(e):
    """(rule_id, level) 집합 — status=confirmed 인 근거."""
    return {(h.get("rule_id"), h.get("level")) for h in hit_details(e) if h.get("status") == "confirmed"}


def review_values(e):
    """review 표시 근거의 (rule_id, review 값) 목록."""
    out = []
    for h in hit_details(e):
        if h.get("review"):
            out.append((h.get("rule_id"), h.get("level"), h.get("review")))
    return out


def fmt_dist(d):
    return ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: (-kv[1], kv[0])))


def legal_axis(old, new, label):
    """(a) REQ-LQMP — 법률 FAIL 구성·review 분포·홀로 선 진료과 권고."""
    rep = {}
    for when, rows in (("old", old), ("new", new)):
        fails = {sid: r for sid, r in rows.items() if ev(r).get("legal_verdict") == "fail"}
        combos = Counter(tuple(sorted(ev(r).get("legal_hits") or [])) for r in fails.values())
        rule_level = Counter()
        lg02_l5 = lg05_l6 = 0
        standalone_care = []          # FAIL 인데 확정 근거가 LG-05 뿐(또는 확정 없음 + review LG-05 뿐)
        review_only = []              # FAIL 인데 호스트 legal_hits 가 빈 배열(근거 전부 review)
        for sid, r in fails.items():
            e = ev(r)
            cr = confirmed_rules(e)
            for rl in cr:
                rule_level[f"{rl[0]} {rl[1]}"] += 1
            if any(rl[0] == "LG-02" and rl[1] == "L5" for rl in cr):
                lg02_l5 += 1
            if any(rl[0] == "LG-05" and rl[1] == "L6" for rl in cr):
                lg05_l6 += 1
            rules = {rl[0] for rl in cr}
            rv_rules = {h.get("rule_id") for h in hit_details(e)}
            if (rules and rules <= {"LG-05"}) or (not rules and rv_rules and rv_rules <= {"LG-05"}):
                standalone_care.append(sid)
            if not e.get("legal_hits"):
                review_only.append(sid)
        # review 값 분포 — 650건 전체(FAIL 아닌 것 포함)
        rv_recs = Counter()
        rv_hits = Counter()
        for r in rows.values():
            vals = review_values(ev(r))
            seen = set()
            for rule, level, val in vals:
                rv_hits[f"{rule} {level} {val}"] += 1
                seen.add(val)
            for v in seen:
                rv_recs[v] += 1
        rv_rules = Counter()
        for r in rows.values():
            for rid in ev(r).get("legal_review_hits") or []:
                rv_rules[str(rid)] += 1
        rep[when] = {
            "fail": len(fails), "fail_ids": sorted(fails),
            "hit_combos": {"+".join(k) or "(없음)": v for k, v in combos.most_common()},
            "confirmed_rule_level_in_fail": dict(rule_level.most_common()),
            "fail_with_LG-02_L5": lg02_l5, "fail_with_LG-05_L6": lg05_l6,
            "standalone_care_fail": standalone_care, "review_only_fail": review_only,
            "review_value_records": dict(rv_recs.most_common()), "review_value_hits": dict(rv_hits.most_common()),
            "legal_review_hits_rules": dict(rv_rules.most_common()),
            "legal_verdict": dist(rows, "legal_verdict"), "verdict": dist(rows, "verdict"),
        }
    rep["moves_legal"] = moves(old, new, "legal_verdict")
    rep["new_fail_from_pass"] = sorted(sid for sid in old if ev(old[sid]).get("legal_verdict") != "fail"
                                      and ev(new.get(sid)).get("legal_verdict") == "fail")
    rep["pass_from_fail"] = sorted(sid for sid in old if ev(old[sid]).get("legal_verdict") == "fail"
                                  and ev(new.get(sid)).get("legal_verdict") != "fail")
    # 기준선 FAIL 이 새 run 에서 어떻게 됐나(review 두 값으로 풀렸는지)
    resolved_by = Counter()
    for sid in rep["pass_from_fail"]:
        vals = {v for _, _, v in review_values(ev(new.get(sid)))}
        key = "+".join(sorted(v for v in vals if v in REVIEW_NEW)) or ("other_review" if vals else "no_hit")
        resolved_by[key] += 1
    rep["pass_from_fail_by_review"] = dict(resolved_by.most_common())
    # 새 FAIL 의 구성(확정 규칙·레벨)
    nf = {}
    for sid in rep["new_fail_from_pass"]:
        nf[sid] = sorted(f"{r} {l}" for r, l in confirmed_rules(ev(new.get(sid))))
    rep["new_fail_rules"] = nf
    return rep


def a2zh_axis(old, new):
    """(b) REQ-A2ZH — 26건 해소 여부 + met→unmet 역방향 전수."""
    rows = []
    resolved = 0
    for sid, ids in A2ZH_ITEMS.items():
        oe, ne = ev(old.get(sid)), ev(new.get(sid))
        for iid in ids:
            key = "validity_items" if iid.startswith("PV") else "uv_items"
            oi = items_by_id(oe, key).get(iid) or {}
            ni = items_by_id(ne, key).get(iid) or {}
            ok = ni.get("result") in ("met", "na")
            resolved += ok
            rows.append({"id": sid, "item": iid, "old": oi.get("result"), "new": ni.get("result"),
                         "new_detail": ni.get("detail"), "new_sentence_idx": ni.get("sentence_idx"),
                         "intent": ne.get("uv_intent"), "resolved": ok,
                         "grade_old": f"{oe.get('validity_grade')}/{oe.get('uv_grade')}",
                         "grade_new": f"{ne.get('validity_grade')}/{ne.get('uv_grade')}"})
    reverse = []        # met → unmet
    na_to_unmet = []    # na → unmet (참고)
    for sid, r in old.items():
        oe, ne = ev(r), ev(new.get(sid))
        for key in ("validity_items", "uv_items"):
            oi, ni = items_by_id(oe, key), items_by_id(ne, key)
            for iid in sorted(set(oi) | set(ni)):
                a, b = (oi.get(iid) or {}).get("result"), (ni.get(iid) or {}).get("result")
                if b == "unmet" and a == "met":
                    reverse.append({"id": sid, "item": iid, "old": a, "new": b, "detail": (ni.get(iid) or {}).get("detail"),
                                    "sentence_idx": (ni.get(iid) or {}).get("sentence_idx"), "intent": ne.get("uv_intent")})
                elif b == "unmet" and a == "na":
                    na_to_unmet.append({"id": sid, "item": iid, "detail": (ni.get(iid) or {}).get("detail"),
                                        "sentence_idx": (ni.get(iid) or {}).get("sentence_idx"), "intent": ne.get("uv_intent")})
    # 항목별 전이 집계(PV·UV 전체)
    trans = defaultdict(Counter)
    for sid, r in old.items():
        oe, ne = ev(r), ev(new.get(sid))
        for key in ("validity_items", "uv_items"):
            oi, ni = items_by_id(oe, key), items_by_id(ne, key)
            for iid in sorted(set(oi) | set(ni)):
                trans[iid][f"{(oi.get(iid) or {}).get('result')}→{(ni.get(iid) or {}).get('result')}"] += 1
    return {"items": rows, "resolved": resolved, "total": len(rows),
            "unresolved": [f"{x['id']} {x['item']}" for x in rows if not x["resolved"]],
            "reverse_met_to_unmet": reverse, "na_to_unmet": na_to_unmet,
            "transitions": {k: dict(sorted(v.items(), key=lambda kv: -kv[1])) for k, v in sorted(trans.items())}}


def pv04_axis(old, new):
    """(c) PR #59 — PV-04 전이와 의도, 3건 참고 등급."""
    trans = Counter()
    trans_intent = Counter()
    remaining_unmet = []
    for sid, r in old.items():
        oe, ne = ev(r), ev(new.get(sid))
        a = (items_by_id(oe, "validity_items").get("PV-04") or {}).get("result")
        ni = items_by_id(ne, "validity_items").get("PV-04") or {}
        b = ni.get("result")
        trans[f"{a}→{b}"] += 1
        trans_intent[f"{a}→{b} | {ne.get('uv_intent')}"] += 1
        if b == "unmet":
            remaining_unmet.append({"id": sid, "intent": ne.get("uv_intent"), "detail": ni.get("detail"), "old": a})
    targets = {}
    for sid in PV04_TARGETS:
        oe, ne = ev(old.get(sid)), ev(new.get(sid))
        targets[sid] = {"grade_old": oe.get("validity_grade"), "grade_new": ne.get("validity_grade"),
                        "source_new": ne.get("validity_grade_source"),
                        "unmet_old": oe.get("validity_unmet"), "unmet_new": ne.get("validity_unmet"),
                        "intent": ne.get("uv_intent"),
                        "pv03_new": (items_by_id(ne, "validity_items").get("PV-03") or {}).get("result"),
                        "pv04_new": (items_by_id(ne, "validity_items").get("PV-04") or {}).get("result"),
                        "uv_grade_new": ne.get("uv_grade"), "verdict_new": ne.get("verdict")}
    return {"transitions": dict(trans.most_common()), "transitions_by_intent": dict(trans_intent.most_common()),
            "remaining_unmet": remaining_unmet,
            "remaining_unmet_by_intent": dict(Counter(x["intent"] for x in remaining_unmet).most_common()),
            "targets": targets}


def sv_axis(old, new, verdicts):
    """(d) REQ-XDIA — 감사 '타당' 항목의 met·키워드 경로 met(LLM 2차 없이), SV 항목 결과 전수 대조."""
    rep = {}
    for when, rows in (("old", old), ("new", new)):
        met = Counter(); kw = Counter()
        for v in verdicts:
            if v.get("run") != "일반 650":
                continue
            e = ev(rows.get(v["id"]))
            items = items_by_id(e, "validity_items")
            for it in v.get("items") or []:
                if it.get("verdict") != "타당":
                    continue
                ni = items.get(it["id"]) or {}
                if ni.get("result") == "met":
                    met[it["id"]] += 1
                    if "llm" not in (ni.get("detail") or ""):
                        kw[it["id"]] += 1
        rep[when] = {"valid_to_met": sum(met.values()), "valid_to_met_by_item": dict(sorted(met.items())),
                     "keyword_path_met": sum(kw.values()), "keyword_path_met_by_item": dict(sorted(kw.items()))}
    same = Counter(); changed = []
    for sid, r in old.items():
        oi, ni = items_by_id(ev(r), "validity_items"), items_by_id(ev(new.get(sid)), "validity_items")
        for iid in sorted(set(oi) | set(ni)):
            a, b = (oi.get(iid) or {}).get("result"), (ni.get(iid) or {}).get("result")
            if a == b:
                same[iid] += 1
            else:
                changed.append({"id": sid, "item": iid, "old": a, "new": b,
                                "llm_old": "llm" in ((oi.get(iid) or {}).get("detail") or ""),
                                "llm_new": "llm" in ((ni.get(iid) or {}).get("detail") or "")})
    rep["items_same_by_item"] = dict(same)
    rep["items_changed"] = changed
    rep["items_changed_by_item"] = dict(Counter(f"{c['item']} {c['old']}→{c['new']}" for c in changed).most_common())
    rep["items_changed_llm_involved"] = sum(1 for c in changed if c["llm_old"] or c["llm_new"])
    rep["validity_grade"] = {"old": grade_dist(old, "validity_grade"), "new": grade_dist(new, "validity_grade")}
    rep["moves_validity"] = moves(old, new, "validity_grade")
    cl = defaultdict(Counter)
    for r in new.values():
        c = ev(r).get("checklist") or {}
        if c:
            cl["version"][str(c.get("version"))] += 1
            cl["match_source"][str(c.get("match_source"))] += 1
            cl["llm_status"][str(c.get("llm_status"))] += 1
            cl["llm_checked>0"][str((c.get("llm_checked") or 0) > 0)] += 1
            cl["emergency_template"][str(c.get("emergency_template"))] += 1
    rep["checklist_new"] = {k: dict(v) for k, v in cl.items()}
    return rep


def meta_axis(rows):
    c = defaultdict(Counter)
    for r in rows.values():
        e = ev(r)
        for k in ("ontology_version", "validity_version", "uv_prompt_version", "legal_version", "claim_fallback",
                  "judge_model", "eval_version", "validity_grade_source", "validity_answer_status"):
            if k in e:
                c[k][str(e.get(k))] += 1
        fc = e.get("fact_check") or {}
        if fc:
            c["fact_check.version"][str(fc.get("version"))] += 1
            c["fact_check.status"][str(fc.get("status"))] += 1
            c["fact_check.fabricated>0"][str((fc.get("fabricated") or 0) > 0)] += 1
        if e.get("error"):
            c["error"]["yes"] += 1
    return {k: dict(v) for k, v in c.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-phr", required=True)
    ap.add_argument("--old-gen", required=True)
    ap.add_argument("--new-phr", required=True)
    ap.add_argument("--new-gen", required=True)
    ap.add_argument("--verdicts-dir", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    ap.add_argument("--title", default="재판정 대조 — 10/16 DEV 1000건: 판정기 v3.23(10/22) → v3.26(18153a9: legal-v11·uv-v15·pv-v5·fact-v9) (2026-10-26)")
    a = ap.parse_args()

    mo_phr, old_phr = load(a.old_phr)
    mo_gen, old_gen = load(a.old_gen)
    mn_phr, new_phr = load(a.new_phr)
    mn_gen, new_gen = load(a.new_gen)
    verdicts = []
    for f in sorted(glob.glob(os.path.join(a.verdicts_dir, "verdicts_*.json"))):
        with open(f, encoding="utf-8") as fh:
            verdicts += json.load(fh)

    rep = {
        "runs": {"old_phr": mo_phr, "old_gen": mo_gen, "new_phr": mn_phr, "new_gen": mn_gen,
                 "n": {"phr": [len(old_phr), len(new_phr)], "gen": [len(old_gen), len(new_gen)]},
                 "missing_in_new": {"phr": sorted(set(old_phr) - set(new_phr)), "gen": sorted(set(old_gen) - set(new_gen))}},
        "meta": {"phr": meta_axis(new_phr), "gen": meta_axis(new_gen)},
        "a_legal_gen": legal_axis(old_gen, new_gen, "일반 650"),
        "a_legal_phr": legal_axis(old_phr, new_phr, "PHR 350"),
        "b_a2zh": a2zh_axis(old_phr, new_phr),
        "c_pv04": pv04_axis(old_phr, new_phr),
        "d_sv_gen": sv_axis(old_gen, new_gen, verdicts),
        "grades_phr": {"validity": {"old": grade_dist(old_phr, "validity_grade"), "new": grade_dist(new_phr, "validity_grade")},
                       "uv": {"old": grade_dist(old_phr, "uv_grade"), "new": grade_dist(new_phr, "uv_grade")},
                       "moves_validity": moves(old_phr, new_phr, "validity_grade"), "moves_uv": moves(old_phr, new_phr, "uv_grade"),
                       "verdict": {"old": dist(old_phr, "verdict"), "new": dist(new_phr, "verdict")}},
        "items_phr": {"old": {**item_dist(old_phr, "validity_items"), **item_dist(old_phr, "uv_items")},
                      "new": {**item_dist(new_phr, "validity_items"), **item_dist(new_phr, "uv_items")}},
    }

    md = [f"# {a.title}", ""]
    md += ["> 읽는 법: LG·UV·PV 축은 판정기 판이 바뀐 비교다(legal-v10→v11, uv-v14→v15, pv-v3→v5, fact-v8→v9). 등급 분포는 참고로만 적고 "
           "v323 과 섞어 비교하지 않는다. 유효성·UV 등급은 참고 등급(진단용, 인수 기준 아님)이며 PHR 350 은 grade_legacy 다. "
           "인수 판단은 법률 게이트·최종 판정·evidence·answer 블록으로 본다. PHR 원문·검진 값은 적지 않는다(문항·항목·문장 번호·건수만).", ""]
    md += ["## 0. run", "", "| | 기준선(v323) | 새 run(v326) |", "|---|---|---|"]
    md.append(f"| PHR 350 | {mo_phr.get('id')} ({mo_phr.get('run_at')}) n {len(old_phr)} | {mn_phr.get('id')} ({mn_phr.get('run_at')}) n {len(new_phr)} |")
    md.append(f"| 일반 650 | {mo_gen.get('id')} ({mo_gen.get('run_at')}) n {len(old_gen)} | {mn_gen.get('id')} ({mn_gen.get('run_at')}) n {len(new_gen)} |")
    for k in ("phr", "gen"):
        if rep["runs"]["missing_in_new"][k]:
            md.append(f"| 새 run 에 없음({k}) | | {len(rep['runs']['missing_in_new'][k])}건 |")
    md.append("")
    md += ["판정기 판(새 run):", ""]
    for k in ("phr", "gen"):
        m = rep["meta"][k]
        md.append(f"- {RUN_LABELS[k]}: " + " · ".join(f"{kk} {fmt_dist(vv)}" for kk, vv in m.items()
                                                      if kk in ("ontology_version", "legal_version", "validity_version", "uv_prompt_version", "fact_check.version", "claim_fallback", "error", "judge_model")))
    md.append("")

    # ── (a) REQ-LQMP ─────────────────────────────────────────────
    L = rep["a_legal_gen"]
    md += ["## (a) REQ-LQMP — 일반 650 법률 게이트 (legal-v10 → legal-v11)", ""]
    md += ["| | 기준선 v323 | 새 run v326 |", "|---|---|---|",
           f"| 법률 FAIL | {L['old']['fail']} | **{L['new']['fail']}** |",
           f"| FAIL 중 확정 LG-02 L5 포함 | {L['old']['fail_with_LG-02_L5']} | {L['new']['fail_with_LG-02_L5']} |",
           f"| FAIL 중 확정 LG-05 L6 포함 | {L['old']['fail_with_LG-05_L6']} | {L['new']['fail_with_LG-05_L6']} |",
           f"| 근거가 모두 review 인 FAIL(legal_hits 빈 배열) | {len(L['old']['review_only_fail'])} | {len(L['new']['review_only_fail'])} |",
           f"| 「홀로 선 진료과 권고」 FAIL(근거가 LG-05 뿐) | {len(L['old']['standalone_care_fail'])} | **{len(L['new']['standalone_care_fail'])}** |",
           f"| 법률 게이트 분포 | {fmt_dist(L['old']['legal_verdict'])} | {fmt_dist(L['new']['legal_verdict'])} |",
           f"| 최종 판정 분포 | {fmt_dist(L['old']['verdict'])} | {fmt_dist(L['new']['verdict'])} |", ""]
    md += ["법률 이동: " + fmt_dist(L["moves_legal"]), ""]
    md += [f"기준선 FAIL → 새 run pass {len(L['pass_from_fail'])}건이 무엇으로 풀렸나(새 run 의 review 값): " + fmt_dist(L["pass_from_fail_by_review"]), ""]
    md += [f"기준선 pass → 새 run FAIL {len(L['new_fail_from_pass'])}건(확정 규칙·레벨): "
           + ("; ".join(f"{sid} [{', '.join(r) or '확정 없음'}]" for sid, r in L["new_fail_rules"].items()) or "없음"), ""]
    md += ["새 run FAIL 의 호스트 legal_hits 조합: " + fmt_dist(L["new"]["hit_combos"]), ""]
    md += ["새 run FAIL 안의 확정 규칙·레벨(건): " + fmt_dist(L["new"]["confirmed_rule_level_in_fail"]), ""]
    md += ["**review 분포(650건 전체, 건수 = 문항 수)**", "", "| review 값 | 기준선 v323 | 새 run v326 |", "|---|---|---|"]
    for v in sorted(set(L["old"]["review_value_records"]) | set(L["new"]["review_value_records"])):
        md.append(f"| {v} | {L['old']['review_value_records'].get(v, 0)} | {L['new']['review_value_records'].get(v, 0)} |")
    md += ["", "review 근거(규칙·레벨·값, 근거 건수) 새 run: " + fmt_dist(L["new"]["review_value_hits"]), ""]
    md += ["legal_review_hits 규칙(문항 수) 기준선 → 새 run: " + fmt_dist(L["old"]["legal_review_hits_rules"]) + " → " + fmt_dist(L["new"]["legal_review_hits_rules"]), ""]
    md += ["새 run 「홀로 선 진료과 권고」 FAIL 잔존: " + (", ".join(L["new"]["standalone_care_fail"]) or "없음"), ""]
    md += ["새 run FAIL 전체 id: " + ", ".join(L["new"]["fail_ids"]), ""]
    P = rep["a_legal_phr"]
    md += [f"PHR 350 법률: FAIL {P['old']['fail']} → {P['new']['fail']} (이동 {fmt_dist(P['moves_legal'])}); review 값 새 run: {fmt_dist(P['new']['review_value_records']) or '없음'}", ""]

    # ── (b) REQ-A2ZH ─────────────────────────────────────────────
    B = rep["b_a2zh"]
    md += ["## (b) REQ-A2ZH — PHR 350 거짓 미충족 26건(21 문항) 해소 여부 (uv-v15·pv-v4·fact-v9)", ""]
    md += [f"해소(met 또는 na) **{B['resolved']} / {B['total']}**. 미해소: " + (", ".join(B["unresolved"]) or "없음"), ""]
    md += ["| 문항 | 항목 | v323 | v326 | 새 detail | 문장 번호 | 의도 | 등급(PV/UV) v323→v326 |", "|---|---|---|---|---|---|---|---|"]
    for x in B["items"]:
        md.append(f"| {x['id'].replace('PHRQR-', '')} | {x['item']} | {x['old']} | **{x['new']}** | {x['new_detail'] or ''} | "
                  f"{','.join(map(str, x['new_sentence_idx'] or [])) or ''} | {x['intent']} | {x['grade_old']}→{x['grade_new']} |")
    md.append("")
    md += [f"**통과(met)→미충족(unmet) 역방향: {len(B['reverse_met_to_unmet'])}건** (PV·UV 모든 항목 전수)", ""]
    if B["reverse_met_to_unmet"]:
        md += ["| 문항 | 항목 | 새 detail | 문장 번호 | 의도 |", "|---|---|---|---|---|"]
        for x in B["reverse_met_to_unmet"]:
            md.append(f"| {x['id'].replace('PHRQR-', '')} | {x['item']} | {x['detail'] or ''} | {','.join(map(str, x['sentence_idx'] or []))} | {x['intent']} |")
        md.append("")
    md += [f"na→unmet(참고): {len(B['na_to_unmet'])}건" + (" — " + ", ".join(f"{x['id'].replace('PHRQR-', '')} {x['item']}" for x in B["na_to_unmet"]) if B["na_to_unmet"] else ""), ""]
    md += ["**항목별 unmet 수·전이(PHR 350, 판정기 판 변경)**", "",
           "| 항목 | v323 unmet | v326 unmet | v326 met | v326 na | unmet→met | unmet→na | met→unmet | na→unmet |",
           "|---|---|---|---|---|---|---|---|---|"]
    for iid in sorted(set(rep["items_phr"]["old"]) | set(rep["items_phr"]["new"])):
        o, n = rep["items_phr"]["old"].get(iid, {}), rep["items_phr"]["new"].get(iid, {})
        t = B["transitions"].get(iid, {})
        md.append(f"| {iid} | {o.get('unmet', 0)} | {n.get('unmet', 0)} | {n.get('met', 0)} | {n.get('na', 0)} | "
                  f"{t.get('unmet→met', 0)} | {t.get('unmet→na', 0)} | {t.get('met→unmet', 0)} | {t.get('na→unmet', 0)} |")
    md.append("")
    G = rep["grades_phr"]
    md += ["참고 등급 분포(PHR 350, grade_legacy, 판정기 판 변경): 유효성 " + " / ".join(f"{g} {G['validity']['old'][g]}→{G['validity']['new'][g]}" for g in (*GRADES, "-"))
           + " · UV " + " / ".join(f"{g} {G['uv']['old'][g]}→{G['uv']['new'][g]}" for g in (*GRADES, "-")), ""]
    md += ["유효성 등급 이동: " + fmt_dist(G["moves_validity"]) + " · UV 등급 이동: " + fmt_dist(G["moves_uv"]), ""]
    md += ["최종 판정(PHR 350): " + fmt_dist(G["verdict"]["old"]) + " → " + fmt_dist(G["verdict"]["new"]), ""]

    # ── (c) PV-04 ────────────────────────────────────────────────
    C = rep["c_pv04"]
    md += ["## (c) PR #59 pv-v5 — PV-04(추세 한 절) 전이 (PHR 350)", ""]
    md += ["PV-04 전이(v323→v326): " + fmt_dist(C["transitions"]), ""]
    md += ["| 전이 | 질문 의도 | 건수 |", "|---|---|---|"]
    for k, v in C["transitions_by_intent"].items():
        tr, intent = k.split(" | ")
        md.append(f"| {tr} | {intent} | {v} |")
    md.append("")
    md += [f"잔존 unmet {len(C['remaining_unmet'])}건의 의도 분류: " + (fmt_dist(C["remaining_unmet_by_intent"]) or "없음"), ""]
    if C["remaining_unmet"]:
        md += ["| 문항 | 의도 | v323 | detail |", "|---|---|---|---|"]
        for x in C["remaining_unmet"]:
            md.append(f"| {x['id'].replace('PHRQR-', '')} | {x['intent']} | {x['old']} | {x['detail'] or ''} |")
        md.append("")
    md += ["**B0052·B0715·B0925 참고 등급(grade_legacy)** — PV-03(#58)+PV-04(#59)로 A 기대", "",
           "| 문항 | 의도 | 등급 v323→v326 | unmet v323 | unmet v326 | PV-03 | PV-04 | UV | 최종 판정 |", "|---|---|---|---|---|---|---|---|---|"]
    for sid, t in C["targets"].items():
        md.append(f"| {sid.replace('PHRQR-', '')} | {t['intent']} | {t['grade_old']}→**{t['grade_new']}**({t['source_new']}) | "
                  f"{','.join(t['unmet_old'] or [])} | {','.join(t['unmet_new'] or []) or '—'} | {t['pv03_new']} | {t['pv04_new']} | {t['uv_grade_new']} | {t['verdict_new']} |")
    md.append("")

    # ── (d) REQ-XDIA ─────────────────────────────────────────────
    D = rep["d_sv_gen"]
    md += ["## (d) REQ-XDIA — 일반 650 SV 키워드 경로 기준선 (sv-v3·cl-v2, 이 run 은 SV 를 바꾸지 않음)", ""]
    md += ["| | 기준선 v323 | 새 run v326 |", "|---|---|---|",
           f"| 감사 '타당' 항목이 met | {D['old']['valid_to_met']} ({fmt_dist(D['old']['valid_to_met_by_item'])}) | {D['new']['valid_to_met']} ({fmt_dist(D['new']['valid_to_met_by_item'])}) |",
           f"| 그중 키워드 경로 met(LLM 2차 없이) | **{D['old']['keyword_path_met']}** ({fmt_dist(D['old']['keyword_path_met_by_item'])}) | **{D['new']['keyword_path_met']}** ({fmt_dist(D['new']['keyword_path_met_by_item'])}) |",
           f"| 유효성(SV) 등급 A/B/C/D | {'/'.join(str(D['validity_grade']['old'][g]) for g in GRADES)} | {'/'.join(str(D['validity_grade']['new'][g]) for g in GRADES)} |", ""]
    md += [f"SV 항목 결과 전수 대조(650건 × SV-01~): 같음 {sum(D['items_same_by_item'].values())} · 다름 {len(D['items_changed'])}"
           f"(그중 LLM 2차가 관여한 항목 {D['items_changed_llm_involved']}) — 다름의 내역: " + (fmt_dist(D["items_changed_by_item"]) or "없음"), ""]
    if D["items_changed"]:
        md += ["다른 항목(문항·항목·전이·LLM 관여): " + "; ".join(f"{c['id']} {c['item']} {c['old']}→{c['new']}{' (llm)' if c['llm_old'] or c['llm_new'] else ''}" for c in D["items_changed"][:80]), ""]
    md += ["SV 등급 이동: " + fmt_dist(D["moves_validity"]), ""]
    md += ["checklist 메타(새 run): " + " · ".join(f"{k} {fmt_dist(v)}" for k, v in D["checklist_new"].items()), ""]

    os.makedirs(os.path.dirname(os.path.abspath(a.out_json)), exist_ok=True)
    with open(a.out_json, "w", encoding="utf-8") as f:
        json.dump(rep, f, ensure_ascii=False, indent=1)
    with open(a.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[compare] wrote {a.out_json} and {a.out_md}")
    print(f"[compare] gen FAIL {L['old']['fail']}→{L['new']['fail']}, standalone care {len(L['new']['standalone_care_fail'])}, "
          f"a2zh resolved {B['resolved']}/{B['total']}, reverse {len(B['reverse_met_to_unmet'])}, "
          f"PV-04 {C['transitions']}, SV keyword met {D['old']['keyword_path_met']}→{D['new']['keyword_path_met']}")


if __name__ == "__main__":
    main()
