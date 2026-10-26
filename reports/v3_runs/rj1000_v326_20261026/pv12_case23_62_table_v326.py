# -*- coding: utf-8 -*-
"""CASE-23·62 의 PV-12 문항별 결과를 두 PHR 350 재판정 덤프(새 run, 기준선 run)에서 뽑아 Markdown 절로 쓴다.

REQ-HMHK 부탁 2 — 10/22 v323 표(rj1000_v323_20261022/pv12_case23_62_20261026.md)에 18153a9(v3.26) run 결과를 덧붙이는 용도.
기록 값(수치·날짜)·답변 원문은 싣지 않는다(문항 id·T·질문·의도·PV-12 결과·detail·참고 등급·unmet 항목만).

    python pv12_case23_62_table_v326.py <new dump> <old dump> <out md>
"""
import json
import re
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
MISS = re.compile(r"기록(이|은|도)?\s*(없|확인되지|찾을 수|보이지)|측정\s*기록\s*없|결과가\s*없|데이터가\s*없|확인할 수 없|기록되어 있지|기록에 없|존재하지")
TARGETS = {"phr_CASE-23", "phr_CASE-62"}


def load(p):
    d = json.load(open(p, encoding="utf-8"))
    recs = d["results_json"] if isinstance(d.get("results_json"), list) else json.loads(d["results_json"])
    return d, {r["scenarioId"]: r for r in recs}


def pv12(r):
    ev = (r or {}).get("evalV3") or {}
    return next((x for x in ev.get("validity_items") or [] if x.get("id") == "PV-12"), {}) or {}


def main():
    dn, new = load(sys.argv[1])
    do, old = load(sys.argv[2])
    out = sys.argv[3]
    rows = []
    for sid, r in new.items():
        if r.get("phrCaseId") not in TARGETS:
            continue
        ev = r["evalV3"]; oev = (old.get(sid) or {}).get("evalV3") or {}
        n, o = pv12(r), pv12(old.get(sid))
        sents = re.split(r"(?<=[.!?])\s+|\n+", (r.get("response") or "").strip())
        miss = [i + 1 for i, s in enumerate(sents) if MISS.search(s)]
        rows.append((r["phrCaseId"], sid, r.get("subcategory"), r.get("prompt"), ev.get("uv_intent"),
                     o.get("result"), n.get("result"), n.get("detail"),
                     f"{oev.get('validity_grade')}→{ev.get('validity_grade')}", ",".join(ev.get("validity_unmet") or []) or "—",
                     f"{oev.get('uv_grade')}→{ev.get('uv_grade')}", ",".join(ev.get("uv_unmet") or []) or "—",
                     ",".join(map(str, miss)) or "—", len(sents),
                     f"{ev.get('legal_verdict')} · evidence {((ev.get('fact_check') or {}).get('status'))}(fab {((ev.get('fact_check') or {}).get('fabricated'))}) · answer {ev.get('validity_answer_status')} · {ev.get('verdict')}"))
    rows.sort(key=lambda x: (x[0], x[1]))
    c_new = Counter(pv12(r).get("result") for r in new.values())
    c_old = Counter(pv12(r).get("result") for r in old.values())
    unmet_new = [(r["phrCaseId"], sid, r.get("subcategory"), pv12(r).get("detail")) for sid, r in new.items() if pv12(r).get("result") == "unmet"]
    md = [f"## 4. 18153a9(v3.26 · pv-v5) 재판정 run 결과 — {dn['id']} ({dn['run_at']}) vs {do['id']}", "",
          "같은 10/16 DEV 답변을 판정기만 바꿔 다시 채점한 것. PV-12 코드는 #57·#58·#59 에서 바뀌지 않았다. 기록 값·답변 원문은 싣지 않는다.", "",
          "| 케이스 | 문항 id | T | 질문 | 의도 | PV-12 v323 | PV-12 v326 | detail(v326) | 참고 등급 PV v323→v326 | PV unmet(v326) | UV v323→v326 | UV unmet(v326) | 결측 문장 번호(호스트 분할) | 총 문장 | 인수 열(v326) |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for x in rows:
        md.append("| " + " | ".join(str(v) for v in x) + " |")
    md += ["", f"v326 run 전체(350문항) PV-12 분포: " + " · ".join(f"{k} {v}" for k, v in c_new.most_common())
           + f" (v323: " + " · ".join(f"{k} {v}" for k, v in c_old.most_common()) + ")",
           "v326 PV-12 unmet: " + "; ".join(f"{c} {s} {t} 「{d}」" for c, s, t, d in unmet_new), ""]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
