# -*- coding: utf-8 -*-
"""v3 시험 세트 구성 — scenario_inventory 결과로 v3 축 기준 세트(1,000건 이상)를 고른다.

(2026-09-29 사용자 결정: v3 축 기준으로 새로 정의, 1,000건 이상. 뽑히지 않은 옛 문항은 은퇴.
빈 칸은 AI 가 새로 쓰고 자동 검사만 거친다.)

세트는 네 구역으로 나눈다. 각 구역의 칸(cell)마다 최소·최대 건수를 두고, 칸 안에서는
기대동작 형식이 좋은 것(v3_rubric > free > none) → 중복 묶음 대표 → id 해시 순으로 고른다.
- PHR   : mode=phr. 의도 9종 칸. PHR 문항은 케이스와 짝이라 모두 넣는다(중복 제외 없음).
- 증상  : mode=symptom. 증상군 42종 × (응급 / 비응급) 칸.
- 법률  : mode=general 이고 유도 규칙(targets)이 있는 것. LG 규칙마다 칸. 한 문항은 자기 규칙 중 후보가
          가장 적은 규칙 칸에 센다(흔한 LG-01~03 에 몰리지 않게). 빈 칸은 세트 전체(증상 문항 포함)에서
          그 규칙을 유도하는 문항 수로 따진다.
- 일반  : mode=general 이고 유도 규칙이 없는 것. 한 칸.
결과(plan)는 문항 id 와 붙일 태그, 은퇴 대상, 빈 칸 목록만 담는다(문장 없음).

    python scripts/build_v3_set.py inventory.json --out plan.json [--set v3set-1]
"""
import argparse
import hashlib
import json
import sys
from collections import Counter, defaultdict

SET_ID = "v3set-1"
INTENTS = ("value_lookup", "trend", "judgment", "timing", "reassurance", "prescription", "scoped",
           "general_with_record", "test_options")
LG_RULES = tuple(f"LG-{i:02d}" for i in range(1, 20))
# 칸별 (최소, 최대). 최소에 못 미치면 빈 칸(gap)으로 보고한다 — AI 신규 작성 대상.
QUOTA = {
    "phr": (20, 10_000),        # 의도마다
    "symptom_emergency": (3, 8),  # 증상군마다 응급 분기
    "symptom_other": (4, 10),     # 증상군마다 당일·외래·생활관리
    "legal": (8, 30),           # LG 규칙마다
    "general": (0, 120),        # 한 칸
}
MIN_TOTAL = 1000
EXP_RANK = {"v3_rubric": 0, "free": 1, "none": 2}


def _h(*p):
    return hashlib.sha1("|".join(p).encode("utf-8")).hexdigest()


def cell_of(r, freq=None):
    c = r.get("cls") or {}
    m = c.get("mode")
    if m == "phr":
        return ("phr", c.get("intent") or "unknown")
    if m == "symptom":
        if not c.get("symptom_key"):
            return ("symptom_unmapped", "-")
        return ("symptom_emergency" if c.get("branch") == "응급" else "symptom_other", c["symptom_key"])
    if m == "general":
        tg = [t for t in c.get("targets") or [] if t in LG_RULES]
        if freq:
            tg = sorted(tg, key=lambda t: (freq.get(t, 0), t))
        return ("legal", tg[0]) if tg else ("general", "-")
    return (m or "none", "-")


def eligible(r):
    c = r.get("cls") or {}
    return (r.get("enabled") and not r.get("retired") and c.get("usable") and c.get("mode") in
            ("phr", "symptom", "general"))


def build(inv, *, set_id=SET_ID, symptom_keys=()):
    rows = inv["rows"]
    # 중복 묶음마다 대표 1건(PHR 은 묶지 않음)
    rep = {}
    for r in rows:
        g = r.get("dup_group")
        if not g or (r.get("cls") or {}).get("mode") == "phr" or not eligible(r):
            continue
        k = (EXP_RANK.get(r.get("expected"), 3), _h(g, r["id"]))
        if g not in rep or k < rep[g][0]:
            rep[g] = (k, r["id"])
    rep_ids = {v[1] for v in rep.values()}
    pool, dropped_dup = [], []
    for r in rows:
        if not eligible(r):
            continue
        if r.get("dup_group") and (r.get("cls") or {}).get("mode") != "phr" and r["id"] not in rep_ids:
            dropped_dup.append(r["id"])
            continue
        pool.append(r)
    freq = Counter(t for r in pool if (r.get("cls") or {}).get("mode") == "general"
                   for t in (r["cls"].get("targets") or []))
    cand = defaultdict(list)
    for r in pool:
        cand[cell_of(r, freq)].append(r)
    picked, gaps = {}, []
    for (zone, key), rs in sorted(cand.items()):
        lo, hi = QUOTA.get(zone, (0, 0))
        rs.sort(key=lambda r: (EXP_RANK.get(r.get("expected"), 3), _h(set_id, r["id"])))
        for r in rs[:hi]:
            picked[r["id"]] = (zone, key)
    # 빈 칸: 정의된 칸 전부에 대해 최소 미달을 센다
    have = Counter(picked.values())
    by_id = {r["id"]: r for r in rows}
    tgt_n = Counter(t for i in picked for t in ((by_id[i].get("cls") or {}).get("targets") or []))
    cells = [("phr", i) for i in INTENTS] + [("legal", g) for g in LG_RULES]
    cells += [(z, k) for k in symptom_keys for z in ("symptom_emergency", "symptom_other")]
    for z, k in cells:
        lo = QUOTA[z][0]
        n = tgt_n[k] if z == "legal" else have[(z, k)]
        if n < lo:
            gaps.append({"zone": z, "key": k, "have": n, "need": lo - n})
    tags = {}
    for i, (z, k) in picked.items():
        c = by_id[i].get("cls") or {}
        t = [f"set:{set_id}", f"zone:{z.replace('symptom_emergency', 'symptom').replace('symptom_other', 'symptom')}",
             f"mode:{c.get('mode')}"]
        if c.get("intent"):
            t.append(f"intent:{c['intent']}")
        if c.get("symptom_key"):
            t.append(f"sym:{c['symptom_key']}")
        if c.get("branch"):
            t.append(f"branch:{c['branch']}")
        t += [f"target:{x}" for x in c.get("targets") or []]
        tags[i] = t
    retire = sorted(r["id"] for r in rows if r.get("enabled") and r["id"] not in picked
                    and (r.get("cls") or {}).get("mode") != "hb" and not r["id"].startswith("HB"))
    zone_n = Counter(z.replace("_emergency", "").replace("_other", "") for z, _ in picked.values())
    return {"set": set_id, "total": len(picked), "min_total": MIN_TOTAL, "zones": dict(zone_n),
            "cells": {f"{z}:{k}": n for (z, k), n in sorted(have.items())},
            "targets": dict(sorted(tgt_n.items())), "gaps": gaps, "gap_total": sum(g["need"] for g in gaps),
            "tags": tags, "retire": retire, "dropped_dup": sorted(dropped_dup),
            "not_eligible": sorted(r["id"] for r in rows if r.get("enabled") and not eligible(r)
                                   and (r.get("cls") or {}).get("mode") != "hb")}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("inventory")
    ap.add_argument("--out", required=True)
    ap.add_argument("--set", default=SET_ID)
    ap.add_argument("--symptom-keys", default="", help="증상군 목록 파일(consultation_checklists.json)")
    a = ap.parse_args(argv)
    inv = json.load(open(a.inventory, encoding="utf-8"))
    keys = ()
    if a.symptom_keys:
        keys = tuple(g["symptom_key"] for g in json.load(open(a.symptom_keys, encoding="utf-8")) if g.get("symptom_key"))
    plan = build(inv, set_id=a.set, symptom_keys=keys)
    json.dump(plan, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(json.dumps({k: plan[k] for k in ("set", "total", "zones", "gap_total")}, ensure_ascii=False))
    print("retire", len(plan["retire"]), "dropped_dup", len(plan["dropped_dup"]),
          "not_eligible", len(plan["not_eligible"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
