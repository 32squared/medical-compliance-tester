# -*- coding: utf-8 -*-
"""[v3] 로그 줄(판정 메타만, 답변 원문 없음)로 PHR 350건 두 실행을 비교한다 — REQ-VXKQ 회신 자료.

  C = phr350r-v3-20260930-1111 (판정기 v3.1 · 온톨로지 v3.8 · legal-v2대 · uv-v6, v18 답변)
  D = phr350r-v4 (판정기 v3.1 · 온톨로지 v3.18 · legal-v7 · pv-v3 · uv-v13, v18 새 답변)

    python phr350r_v4_compare.py <dir> [C_log] [D_log] [remap.json]
    <dir>/C_0930.log · <dir>/D_v4.log 는 Cloud Logging 의 `[v3] PHRQR-…` 줄,
    remap.json 은 scripts/scenarios_phr_case_350_remap.json (subcategory=T 유형).
결과 <dir>/compare_v4.json — 세 축 분포·전이·법률 fail id 와 hits·REQ-0013 범위 id 의 전후 verdict·T3·유형별.
답변 원문·케이스 수치는 들어가지 않는다(id·건수·규칙 id 만).
"""
import ast
import json
import re
import sys
from collections import Counter

D = sys.argv[1]
C_LOG = sys.argv[2] if len(sys.argv) > 2 else f"{D}/C_0930.log"
D_LOG = sys.argv[3] if len(sys.argv) > 3 else f"{D}/D_v4.log"
REMAP = sys.argv[4] if len(sys.argv) > 4 else "scripts/scenarios_phr_case_350_remap.json"

LINE = re.compile(r"\[v3\] (\S+) v2=\S+ verdict=(\S+) legal=(\w+) hits=(\[.*?\]) review=(\[.*?\]) "
                  r"(?:PV|SV)=(\S+) unmet=(\[.*?\]) UV=(\S+) unmet=(\[.*?\]) intent=(\S+) prompt=(\S+) skip=(\S+) "
                  r"claims=(\d+) fallback=(\d+)(?: ttft=(\S+) total=(\S+) len=(\d+))?(?: escalated=(\S+))?")

# REQ-0013 재판정 범위 가운데 이 350문항 세트에 있는 id (general100 의 DIAG-097 등은 다른 세트라 제외)
REQ0013_IDS = {
    "run0102_fail": ["PHRQR-B0108", "PHRQR-B0441", "PHRQR-B0977"],
    "run0102_pass_to_fail": ["PHRQR-B0022", "PHRQR-B0199", "PHRQR-B0325", "PHRQR-B0427", "PHRQR-B0564"],
    "run0930_T7": ["PHRQR-B0325", "PHRQR-B0564"],
}


def load(path):
    out = {}
    for ln in open(path, encoding="utf-8-sig"):
        m = LINE.search(ln)
        if not m:
            continue
        g = m.groups()
        out[g[0]] = {"verdict": g[1], "legal": g[2], "hits": ast.literal_eval(g[3]), "review": ast.literal_eval(g[4]),
                     "pv": g[5], "pv_unmet": ast.literal_eval(g[6]), "uv": g[7], "uv_unmet": ast.literal_eval(g[8]),
                     "intent": g[9], "prompt": g[10], "skip": g[11], "claims": int(g[12]), "fallback": int(g[13]),
                     "len": int(g[16] or 0), "esc": g[17]}
    return out


raw = json.load(open(REMAP, encoding="utf-8"))
rows = raw if isinstance(raw, list) else raw.get("scenarios") or raw.get("rows")
qtype = {r["id"]: r.get("subcategory") or "?" for r in rows}
runs = {"C": load(C_LOG), "D": load(D_LOG)}
out = {"n": {k: len(v) for k, v in runs.items()}, "missing_in_D": sorted(set(runs["C"]) - set(runs["D"]))}


def dist(key, rs):
    return dict(sorted(Counter(str(r[key]) for r in rs.values()).items()))


def unmet(key, rs):
    return dict(sorted(Counter(x for r in rs.values() for x in r[key]).items()))


for k, rs in runs.items():
    if not rs:
        continue
    out[k] = {"legal": dist("legal", rs), "rule_hits": unmet("hits", rs), "review_hits": unmet("review", rs),
              "pv": dist("pv", rs), "uv": dist("uv", rs), "intent": dist("intent", rs), "prompt": dist("prompt", rs),
              "skip": dist("skip", rs), "pv_unmet": unmet("pv_unmet", rs), "uv_unmet": unmet("uv_unmet", rs),
              "escalated": sum(1 for r in rs.values() if r["esc"]),
              "fallback_items": sum(1 for r in rs.values() if r["fallback"]),
              "len_avg": round(sum(r["len"] for r in rs.values()) / max(1, len(rs))),
              "claims_avg": round(sum(r["claims"] for r in rs.values()) / max(1, len(rs)), 1),
              "all_A": sum(1 for r in rs.values() if r["legal"] == "pass" and r["pv"] == "A" and r["uv"] == "A"),
              "legal_fail": {i: r["hits"] for i, r in sorted(rs.items()) if r["legal"] == "fail"}}
    by_q = {}
    for i, r in rs.items():
        d = by_q.setdefault(qtype.get(i, "?"), Counter())
        d["n"] += 1
        d["legal_fail"] += r["legal"] == "fail"
        d[f"pv_{r['pv']}"] += 1
        d[f"uv_{r['uv']}"] += 1
    out[k]["by_qtype"] = {q: dict(d) for q, d in sorted(by_q.items(), key=lambda kv: int(kv[0][1:]) if kv[0][1:].isdigit() else 99)}
    t3 = [i for i in rs if qtype.get(i) == "T3"]
    out[k]["T3"] = {"n": len(t3), "legal_fail": sum(rs[i]["legal"] == "fail" for i in t3),
                    "pv": dict(Counter(rs[i]["pv"] for i in t3)), "uv": dict(Counter(rs[i]["uv"] for i in t3)),
                    "pv_unmet": dict(Counter(x for i in t3 for x in rs[i]["pv_unmet"]).most_common()),
                    "legal_hits": dict(Counter(x for i in t3 for x in rs[i]["hits"]))}

C, Dd = runs["C"], runs["D"]
if C and Dd:
    ids = sorted(set(C) & set(Dd))

    def trans(key):
        return dict(Counter(f"{C[i][key]}→{Dd[i][key]}" for i in ids).most_common())

    out["C→D"] = {"legal": trans("legal"), "pv": trans("pv"), "uv": trans("uv"),
                  "intent_changed": sum(1 for i in ids if C[i]["intent"] != Dd[i]["intent"]),
                  "legal_flips": {i: f"{C[i]['legal']}{C[i]['hits']}→{Dd[i]['legal']}{Dd[i]['hits']}"
                                  for i in ids if C[i]["legal"] != Dd[i]["legal"]}}
    out["REQ-0013"] = {grp: {i: {"C_0930": f"{C[i]['legal']}{C[i]['hits']}" if i in C else None,
                                 "D_v4": f"{Dd[i]['legal']}{Dd[i]['hits']}" if i in Dd else None}
                             for i in lst} for grp, lst in REQ0013_IDS.items()}
json.dump(out, open(f"{D}/compare_v4.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps({k: out[k] for k in out if k in ("n", "missing_in_D", "C→D", "REQ-0013")}, ensure_ascii=False, indent=1))
for k in ("C", "D"):
    if k in out:
        print(k, "legal", out[k]["legal"], "pv", out[k]["pv"], "uv", out[k]["uv"], "allA", out[k]["all_A"],
              "esc", out[k]["escalated"], "T3", out[k]["T3"]["legal_fail"], out[k]["T3"]["pv"])
