# -*- coding: utf-8 -*-
"""정답지(골드셋) 라벨 — 검증·판정기 스냅샷·일치율 계산 (평가체계 개선 계획 1단계).

사람이 v3 판정 결과를 검토해 붙인 정답을 저장한다. 판정기 정확도(LG 정밀도·재현율, 항목 일치율)와
검토자 간 일치(교차 라벨)의 재료다. 저장은 db.save_gold_label, 화면은 review.html, API 는
/api/eval-v3/labels · /api/eval-v3/review-item (proxy_server.py).

라벨 형식:
    {"legal": {"verdict": "pass"|"fail", "rules": ["LG-02", ...], "note": "..."},
     "items": {"PV-01": "met"|"unmet"|"na", "UV-02": ..., "SV-03": ...}}
판정기 스냅샷(judge)은 라벨을 저장할 때 서버가 그 결과의 evalV3 에서 떠 둔다 — 나중에 재판정으로
결과가 바뀌어도 '그때 판정기가 뭐라 했고 사람이 뭐라 했는지' 가 남는다.
"""
import json
import re

LEGAL_VERDICTS = ("pass", "fail")
ITEM_VALUES = ("met", "unmet", "na")
_RULE = re.compile(r"^LG-\d{2}$")
_ITEM = re.compile(r"^(PV|SV|UV)-\d{2}[a-z]?$")


def validate(labels):
    """라벨 dict → (정리된 라벨, 오류 목록)."""
    errs = []
    if not isinstance(labels, dict):
        return None, ["labels 는 객체여야 합니다"]
    legal = labels.get("legal") or {}
    verdict = str(legal.get("verdict") or "").lower()
    if verdict not in LEGAL_VERDICTS:
        errs.append("legal.verdict 는 pass|fail")
    rules = [str(r).strip() for r in (legal.get("rules") or []) if str(r).strip()]
    bad = [r for r in rules if not _RULE.match(r)]
    if bad:
        errs.append(f"legal.rules 형식 오류: {bad[:5]}")
    if verdict == "pass" and rules:
        errs.append("legal pass 인데 rules 가 있습니다")
    if verdict == "fail" and not rules:
        errs.append("legal fail 이면 걸린 규칙(rules)을 하나 이상 적어야 합니다")
    items = {}
    for k, v in (labels.get("items") or {}).items():
        k, v = str(k).strip(), str(v or "").strip().lower()
        if not _ITEM.match(k):
            errs.append(f"항목 id 형식 오류: {k}")
        elif v not in ITEM_VALUES:
            errs.append(f"{k}: 값은 met|unmet|na")
        else:
            items[k] = v
    clean = {"legal": {"verdict": verdict, "rules": sorted(set(rules)),
                       "note": str(legal.get("note") or "").strip()[:1000]},
             "items": items}
    return clean, errs


def judge_snapshot(result):
    """이력 결과 1건 → 라벨과 비교할 판정기 값(원문 없음)."""
    v3 = (result or {}).get("evalV3") or {}
    items = {}
    for it in (v3.get("validity_items") or []) + (v3.get("uv_items") or []):
        if isinstance(it, dict) and it.get("id"):
            items[str(it["id"])] = it.get("result")
    orig = v3.get("judge_original") or {}
    return {
        "legal_verdict": orig.get("legal_verdict") or v3.get("legal_verdict"),
        "legal_hits": list(orig.get("legal_hits") or v3.get("legal_hits") or []),
        "human_review": (v3.get("human_review") or {}).get("verdict"),
        "validity_axis": v3.get("validity_axis"), "validity_grade": v3.get("validity_grade"),
        "uv_grade": v3.get("uv_grade"), "uv_intent": v3.get("uv_intent"),
        "items": items,
        "ontology_version": v3.get("ontology_version"), "judge_model": v3.get("judge_model"),
        "eval_version": v3.get("eval_version"),
    }


def agreement(rows):
    """라벨 목록 → 판정기 대비 지표 + 검토자 간 일치.

    LG: 사람 라벨을 정답으로 보고 판정기 fail 의 정밀도·재현율. 항목: 판정기 값이 met|unmet|na 인 것만
    비교(not_scored 제외). 교차: 같은 (run, 문항)에 검토자가 둘 이상이면 법률 판정 일치 비율.
    """
    tp = fp = fn = tn = 0
    item_n = item_same = 0
    per_item = {}
    for r in rows or []:
        lab, jd = r.get("labels") or {}, r.get("judge") or {}
        h = (lab.get("legal") or {}).get("verdict")
        j = jd.get("legal_verdict")
        if h in LEGAL_VERDICTS and j in LEGAL_VERDICTS:
            if j == "fail" and h == "fail":
                tp += 1
            elif j == "fail":
                fp += 1
            elif h == "fail":
                fn += 1
            else:
                tn += 1
        for k, hv in (lab.get("items") or {}).items():
            jv = (jd.get("items") or {}).get(k)
            if jv not in ITEM_VALUES:
                continue
            item_n += 1
            same = jv == hv
            item_same += same
            s = per_item.setdefault(k, [0, 0])
            s[0] += 1
            s[1] += same
    by_key = {}
    for r in rows or []:
        v = ((r.get("labels") or {}).get("legal") or {}).get("verdict")
        if v:
            by_key.setdefault((r.get("runId"), r.get("scenarioId")), {})[r.get("labelerId")] = v
    cross = [vs for vs in by_key.values() if len(vs) >= 2]
    cross_same = sum(1 for vs in cross if len(set(vs.values())) == 1)

    def ratio(a, b):
        return round(a / b, 4) if b else None

    return {
        "n": len(rows or []), "items_labeled": len(by_key),
        "legal": {"tp": tp, "fp": fp, "fn": fn, "tn": tn,
                  "precision": ratio(tp, tp + fp), "recall": ratio(tp, tp + fn)},
        "items": {"n": item_n, "agree": ratio(item_same, item_n),
                  "by_id": {k: {"n": v[0], "agree": ratio(v[1], v[0])} for k, v in sorted(per_item.items())}},
        "cross": {"pairs": len(cross), "legal_agree": ratio(cross_same, len(cross))},
    }


_RULE_NAMES = None


def rule_names():
    """온톨로지 규칙 id → {title, required} (LG·PV·SV·UV). 판정기를 못 쓰면 {}."""
    global _RULE_NAMES
    if _RULE_NAMES is None:
        try:
            import eval_v3
            snap = eval_v3.get_snapshot()
            _RULE_NAMES = {str(r["id"]): {"title": r.get("title") or "", "required": bool(r.get("required")),
                                          "level": r.get("level") or "", "note": r.get("note") or ""}
                           for r in snap.table("rule") if r.get("id") and not r.get("version_to")}
        except Exception:
            _RULE_NAMES = {}
    return _RULE_NAMES


def ai_meta(row):
    """AI 검수 라벨(scripts/ai_verify.py)의 note JSON → dict. 사람 라벨·깨진 값이면 {}."""
    if not str((row or {}).get('labelerId') or '').startswith('ai:'):
        return {}
    try:
        m = json.loads(row.get('note') or '{}')
    except (TypeError, ValueError):
        return {}
    return m if isinstance(m, dict) else {}
