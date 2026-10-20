"""10/16 DEV 1000건(PHR 350·일반 650) 재판정(판정기 v3.20 + cl-v2 + symptomKey) 전후 비교.

입력: 원본 덤프 2개(10/16)와 재판정 덤프 2개(rj1000-*-v320-20261020), C 이하 등급 감사 판정(cd_audit_20261019/verdicts_*.json).
출력: JSON(집계)과 Markdown(표) — 등급 분포 전후, 등급 이동, 감사에서 '거짓/경계/타당' 으로 본 항목이 새 판정에서
      met/na/unmet 중 무엇이 됐는지, 남은 D, 새 판정의 체크리스트 판·증상군 매칭 출처·LLM 2차 확인·응급 템플릿 통계.

사용:
  python compare_rejudge_v320.py --old-phr <json> --old-gen <json> --new-phr <json> --new-gen <json> \
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


def load_rows(path):
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    rows = d["results_json"] if isinstance(d, dict) else d
    return {r["scenarioId"]: r for r in rows if isinstance(r, dict) and r.get("scenarioId")}


def ev(r):
    e = (r or {}).get("evalV3") or {}
    return e if isinstance(e, dict) else {}


def items_by_id(e, key):
    return {i["id"]: i for i in (e.get(key) or []) if isinstance(i, dict) and i.get("id")}


def grade_dist(rows, key):
    c = Counter()
    for r in rows.values():
        c[str(ev(r).get(key) or "-")] += 1
    return {g: c.get(g, 0) for g in (*GRADES, "-")}


def legal_dist(rows):
    return dict(Counter(str(ev(r).get("legal_verdict") or "-") for r in rows.values()))


def verdict_dist(rows):
    return dict(Counter(str(ev(r).get("verdict") or "-") for r in rows.values()))


def moves(old, new, key):
    m = Counter()
    for sid, r in old.items():
        a = str(ev(r).get(key) or "-")
        b = str(ev(new.get(sid)).get(key) or "-")
        m[f"{a}→{b}"] += 1
    return dict(sorted(m.items(), key=lambda kv: (-kv[1], kv[0])))


def item_dist(rows, key):
    """항목 id 별 met/na/unmet 분포."""
    out = defaultdict(Counter)
    for r in rows.values():
        for i in ev(r).get(key) or []:
            if isinstance(i, dict) and i.get("id"):
                out[i["id"]][str(i.get("result"))] += 1
    return {k: dict(v) for k, v in sorted(out.items())}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old-phr", required=True)
    ap.add_argument("--old-gen", required=True)
    ap.add_argument("--new-phr", required=True)
    ap.add_argument("--new-gen", required=True)
    ap.add_argument("--verdicts-dir", required=True)
    ap.add_argument("--out-json", required=True)
    ap.add_argument("--out-md", required=True)
    a = ap.parse_args()

    runs = {
        "phr": (load_rows(a.old_phr), load_rows(a.new_phr)),
        "gen": (load_rows(a.old_gen), load_rows(a.new_gen)),
    }
    verdicts = []
    for f in sorted(glob.glob(os.path.join(a.verdicts_dir, "verdicts_*.json"))):
        with open(f, encoding="utf-8") as fh:
            verdicts += json.load(fh)

    report = {"runs": {}, "audit": {}, "remaining_d": [], "new_meta": {}}
    md = ["# 재판정 전후 비교 — 10/16 DEV 1000건 → 판정기 v3.20 + cl-v2 + symptomKey (2026-10-20)", ""]

    # ── 1. 등급 분포·이동 ────────────────────────────────────────────
    for key, (old, new) in runs.items():
        label = RUN_LABELS[key]
        missing = sorted(set(old) - set(new))
        rr = {
            "n_old": len(old), "n_new": len(new), "missing_in_new": missing,
            "validity_grade": {"old": grade_dist(old, "validity_grade"), "new": grade_dist(new, "validity_grade")},
            "uv_grade": {"old": grade_dist(old, "uv_grade"), "new": grade_dist(new, "uv_grade")},
            "legal_verdict": {"old": legal_dist(old), "new": legal_dist(new)},
            "verdict": {"old": verdict_dist(old), "new": verdict_dist(new)},
            "moves_validity": moves(old, new, "validity_grade"),
            "moves_uv": moves(old, new, "uv_grade"),
            "moves_legal": moves(old, new, "legal_verdict"),
            "items_validity": {"old": item_dist(old, "validity_items"), "new": item_dist(new, "validity_items")},
            "items_uv": {"old": item_dist(old, "uv_items"), "new": item_dist(new, "uv_items")},
        }
        report["runs"][key] = rr
        md += [f"## {label} — n {len(old)} → {len(new)}" + (f" (새 run 에 없음 {len(missing)}건)" if missing else ""), ""]
        for gk, title in (("validity_grade", "유효성(PV/SV) 등급"), ("uv_grade", "사용자 가치(UV) 등급")):
            md += [f"**{title}**", "", "| | A | B | C | D | 없음 |", "|---|---|---|---|---|---|"]
            for when in ("old", "new"):
                d = rr[gk][when]
                md.append(f"| {'10/16' if when == 'old' else '재판정'} | {d['A']} | {d['B']} | {d['C']} | {d['D']} | {d['-']} |")
            md.append("")
        md += ["**법률 게이트** 10/16 → 재판정: " + json.dumps(rr["legal_verdict"]["old"], ensure_ascii=False)
               + " → " + json.dumps(rr["legal_verdict"]["new"], ensure_ascii=False), ""]
        md += ["**최종 판정(verdict)** 10/16 → 재판정: " + json.dumps(rr["verdict"]["old"], ensure_ascii=False)
               + " → " + json.dumps(rr["verdict"]["new"], ensure_ascii=False), ""]
        md += ["유효성 등급 이동(상위): " + ", ".join(f"{k} {v}" for k, v in list(rr["moves_validity"].items())[:12]), ""]
        md += ["UV 등급 이동(상위): " + ", ".join(f"{k} {v}" for k, v in list(rr["moves_uv"].items())[:12]), ""]
        md += ["법률 이동: " + ", ".join(f"{k} {v}" for k, v in rr["moves_legal"].items()), ""]
        md += ["| 항목 | 10/16 unmet | 재판정 unmet | 재판정 met | 재판정 na |", "|---|---|---|---|---|"]
        for ik in ("items_validity", "items_uv"):
            ids = sorted(set(rr[ik]["old"]) | set(rr[ik]["new"]))
            for i in ids:
                o = rr[ik]["old"].get(i, {})
                n = rr[ik]["new"].get(i, {})
                md.append(f"| {i} | {o.get('unmet', 0)} | {n.get('unmet', 0)} | {n.get('met', 0)} | {n.get('na', 0)} |")
        md.append("")

    # ── 2. 감사 판정 → 새 결과 ───────────────────────────────────────
    cross = defaultdict(Counter)          # verdict → new result
    cross_item = defaultdict(Counter)     # (item id, verdict) → new result
    false_detail = []                     # 거짓인데 여전히 unmet
    grade_after = Counter()               # 감사 대상 277건의 새 등급
    label2key = {v: k for k, v in RUN_LABELS.items()}
    for v in verdicts:
        key = label2key.get(v["run"])
        if not key:
            continue
        old, new = runs[key]
        nr = ev(new.get(v["id"]))
        vit = items_by_id(nr, "validity_items")
        uit = items_by_id(nr, "uv_items")
        grade_after[f"validity:{nr.get('validity_grade') or '-'}"] += 1
        grade_after[f"uv:{nr.get('uv_grade') or '-'}"] += 1
        for it in v["items"]:
            iid = it["id"]
            src = vit if iid[:2] in ("PV", "SV") else uit
            res = (src.get(iid) or {}).get("result") or ("없음" if v["id"] in new else "run없음")
            cross[it["verdict"]][res] += 1
            cross_item[(iid, it["verdict"])][res] += 1
            if it["verdict"] == "거짓" and res == "unmet":
                false_detail.append({"run": v["run"], "id": v["id"], "item": iid, "pattern": it.get("pattern"),
                                     "old_reason": it.get("reason"), "new_detail": (src.get(iid) or {}).get("detail")})
    report["audit"] = {
        "cases": len(verdicts),
        "cross": {k: dict(c) for k, c in cross.items()},
        "cross_item": {f"{i}|{vd}": dict(c) for (i, vd), c in sorted(cross_item.items())},
        "false_still_unmet": false_detail,
        "grade_after": dict(grade_after),
    }
    md += ["## 감사(DOC-T6VZ4) 판정 항목이 재판정에서 어떻게 됐나 — C 이하 277건", "",
           "| 감사 판정 | met | na | unmet | 항목 없음 | 합 |", "|---|---|---|---|---|---|"]
    for vd in ("거짓", "경계", "타당", "확인불가"):
        c = cross.get(vd, Counter())
        md.append(f"| {vd} | {c.get('met', 0)} | {c.get('na', 0)} | {c.get('unmet', 0)} | "
                  f"{c.get('없음', 0) + c.get('run없음', 0)} | {sum(c.values())} |")
    md += ["", "항목별(거짓만):", "", "| 항목 | met | na | unmet | 없음 |", "|---|---|---|---|---|"]
    for (i, vd), c in sorted(cross_item.items()):
        if vd == "거짓":
            md.append(f"| {i} | {c.get('met', 0)} | {c.get('na', 0)} | {c.get('unmet', 0)} | {c.get('없음', 0)} |")
    md += ["", f"거짓인데 여전히 unmet: {len(false_detail)}건", ""]
    for fd in false_detail[:60]:
        md.append(f"- {fd['run']} {fd['id']} {fd['item']} [{fd['pattern']}] → 새 detail: {fd['new_detail']}")
    md.append("")

    # ── 3. 남은 D ───────────────────────────────────────────────────
    for key, (old, new) in runs.items():
        for sid, r in new.items():
            e = ev(r)
            if e.get("validity_grade") == "D" or e.get("uv_grade") == "D":
                oe = ev(old.get(sid))
                report["remaining_d"].append({
                    "run": RUN_LABELS[key], "id": sid, "axis": e.get("validity_axis"),
                    "validity": f"{oe.get('validity_grade')}→{e.get('validity_grade')}",
                    "uv": f"{oe.get('uv_grade')}→{e.get('uv_grade')}",
                    "v_unmet": e.get("validity_unmet"), "uv_unmet": e.get("uv_unmet"),
                    "grade_cap": e.get("grade_cap"), "legal": e.get("legal_verdict"),
                })
    md += [f"## 재판정 뒤 D 등급(유효성 또는 UV) — {len(report['remaining_d'])}건", "",
           "| run | id | 축 | 유효성 | UV | 유효성 unmet | UV unmet | cap |", "|---|---|---|---|---|---|---|---|"]
    for d in report["remaining_d"]:
        md.append(f"| {d['run']} | {d['id']} | {d['axis']} | {d['validity']} | {d['uv']} | "
                  f"{','.join(d['v_unmet'] or [])} | {','.join(d['uv_unmet'] or [])} | {d['grade_cap'] or ''} |")
    md.append("")

    # ── 4. 새 판정 메타 ──────────────────────────────────────────────
    meta = {}
    for key, (old, new) in runs.items():
        c = defaultdict(Counter)
        for r in new.values():
            e = ev(r)
            c["ontology_version"][str(e.get("ontology_version"))] += 1
            c["validity_version"][str(e.get("validity_version"))] += 1
            c["uv_prompt_version"][str(e.get("uv_prompt_version"))] += 1
            c["legal_version"][str(e.get("legal_version"))] += 1
            c["claim_fallback"][str(e.get("claim_fallback"))] += 1
            c["gate_mode"][str(e.get("gate_mode"))] += 1
            cl = e.get("checklist") or {}
            if cl:
                c["checklist.version"][str(cl.get("version"))] += 1
                c["checklist.match_source"][str(cl.get("match_source"))] += 1
                c["checklist.symptom_key_none"][str(cl.get("symptom_key") in (None, "none"))] += 1
                c["checklist.emergency_template"][str(cl.get("emergency_template"))] += 1
                c["checklist.llm_checked>0"][str((cl.get("llm_checked") or 0) > 0)] += 1
                c["checklist.llm_status"][str(cl.get("llm_status"))] += 1
                c["checklist.judge_model"][str(cl.get("judge_model"))] += 1
                c["checklist.lg16"][str(cl.get("lg16"))] += 1
                c["checklist.branch"][str(cl.get("branch"))] += 1
            fc = e.get("fact_check") or {}
            if fc:
                c["fact_check.status"][str(fc.get("status"))] += 1
                c["fact_check.fabricated>0"][str((fc.get("fabricated") or 0) > 0)] += 1
        meta[key] = {k: dict(v) for k, v in c.items()}
    report["new_meta"] = meta
    md += ["## 재판정 결과 메타", ""]
    for key in runs:
        md += [f"**{RUN_LABELS[key]}**", ""]
        for k, v in meta[key].items():
            md.append(f"- {k}: " + ", ".join(f"{kk} {vv}" for kk, vv in sorted(v.items(), key=lambda kv: -kv[1])))
        md.append("")

    os.makedirs(os.path.dirname(os.path.abspath(a.out_json)), exist_ok=True)
    with open(a.out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(a.out_md, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"[compare] wrote {a.out_json} and {a.out_md}")
    print("[compare] audit cross:", json.dumps(report["audit"]["cross"], ensure_ascii=False))
    print("[compare] remaining D:", len(report["remaining_d"]))


if __name__ == "__main__":
    main()
