"""
rag_gap_analysis.py — 평가→수집 환류 루프 (데이터 수집 전략 Phase 3 핵심).

rag_queries의 근거 부족(evidence_quality=insufficient/low) 질의를 intent·증상별로
집계해 **근거 보강이 필요한 주제 우선순위 큐**를 산출한다. = "평가가 수집을 견인".

실행:
  python rag_gap_analysis.py                 # 최근 2000건 분석 → 우선순위 출력
  python rag_gap_analysis.py --limit 5000

순수 집계 함수 aggregate_gaps()는 rag_queries 행 리스트를 받아 DB 없이 테스트 가능.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from typing import Dict, List, Tuple

_DIR = os.path.dirname(os.path.abspath(__file__))
_CHECKLISTS_JSON = os.path.join(_DIR, "consultation_checklists.json")
_INSUFFICIENT = {"insufficient", "low", "LOW", "INSUFFICIENT"}


def _load_symptom_keywords() -> Dict[str, List[str]]:
    """consultation_checklists → {symptom_name: [keywords]} (증상 매핑용)."""
    try:
        with open(_CHECKLISTS_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    out: Dict[str, List[str]] = {}
    for s in data:
        name = s.get("symptom_name", "")
        kws = set()
        if name:
            kws.add(name)
        for d in (s.get("detail", "") or "").split(","):
            d = d.strip()
            if d:
                kws.add(d)
        out[name] = [k for k in kws if k]
    return out


def _match_symptom(query: str, sym_kw: Dict[str, List[str]]) -> str:
    """질의에서 매칭되는 증상명 1개(첫 매칭) 반환, 없으면 'unmapped'."""
    for name, kws in sym_kw.items():
        for kw in kws:
            if kw and kw in query:
                return name
    return "unmapped"


def aggregate_gaps(rows: List[Dict], sym_kw: Dict[str, List[str]] = None) -> Dict:
    """rag_queries 행 리스트 → gap 집계 (순수 함수).

    rows item: {query_text, evidence_quality, classification_json}
    """
    sym_kw = sym_kw if sym_kw is not None else {}
    by_quality = collections.Counter()
    by_intent = collections.Counter()       # insufficient 질의의 intent 분포
    by_symptom = collections.Counter()       # insufficient 질의의 증상 분포
    samples: Dict[str, List[str]] = collections.defaultdict(list)
    total = 0
    insuff = 0

    for r in rows:
        total += 1
        q = (r.get("evidence_quality") or "unknown")
        by_quality[q] += 1
        if q not in _INSUFFICIENT:
            continue
        insuff += 1
        qt = r.get("query_text") or ""
        intent = "unknown"
        cj = r.get("classification_json")
        if cj:
            try:
                intent = (json.loads(cj) or {}).get("intent", "unknown")
            except Exception:
                pass
        by_intent[intent] += 1
        sym = _match_symptom(qt, sym_kw)
        by_symptom[sym] += 1
        if len(samples[sym]) < 3:
            samples[sym].append(qt[:60])

    # 수집 우선순위: insufficient 건수 많은 증상/intent 순
    priority = [
        {"symptom": sym, "insufficient_count": cnt, "samples": samples.get(sym, [])}
        for sym, cnt in by_symptom.most_common()
        if sym != "unmapped"
    ]
    return {
        "total": total,
        "insufficient": insuff,
        "insufficient_rate": round(insuff / total, 3) if total else 0.0,
        "by_quality": dict(by_quality),
        "by_intent_insufficient": dict(by_intent.most_common()),
        "collection_priority": priority,
        "unmapped_insufficient": by_symptom.get("unmapped", 0),
    }


def run(limit: int = 2000) -> Dict:
    import db
    rows: List[Dict] = []
    with db.get_conn() as (conn, cur):
        cur.execute(
            "SELECT query_text, evidence_quality, classification_json "
            "FROM rag_queries ORDER BY created_at DESC LIMIT %s",
            (limit,),
        )
        for r in cur.fetchall():
            rows.append(dict(r) if hasattr(r, "keys") else
                        {"query_text": r[0], "evidence_quality": r[1], "classification_json": r[2]})
    return aggregate_gaps(rows, _load_symptom_keywords())


def main():
    ap = argparse.ArgumentParser(description="평가→수집 환류: 근거부족 질의 주제별 집계")
    ap.add_argument("--limit", type=int, default=2000)
    args = ap.parse_args()
    res = run(limit=args.limit)
    print("===GAP_ANALYSIS_BEGIN===", flush=True)
    print(json.dumps({
        "total": res["total"], "insufficient": res["insufficient"],
        "insufficient_rate": res["insufficient_rate"],
        "by_quality": res["by_quality"],
        "by_intent_insufficient": res["by_intent_insufficient"],
        "unmapped_insufficient": res["unmapped_insufficient"],
    }, ensure_ascii=False), flush=True)
    print("--- 수집 우선순위 (근거부족 많은 증상 순) ---", flush=True)
    for i, p in enumerate(res["collection_priority"][:20], 1):
        print(f"{i:2d}. {p['symptom']}  부족={p['insufficient_count']}  예: {p['samples'][:2]}", flush=True)
    print("===GAP_ANALYSIS_END===", flush=True)


if __name__ == "__main__":
    main()
