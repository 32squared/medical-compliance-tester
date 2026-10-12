# -*- coding: utf-8 -*-
"""저장된 답변에서 '의사·의료진 없이 약사만 넣어 끝맺은 문장'이 있는 답변 수를 센다 (REQ-VXKQ 4번, 법무 문의 후보 근거).

Cloud Run Job 안에서 돈다(DB 가 private IP). 답변 원문은 출력하지 않는다 — id·건수만.
    COUNT_RUNS=run1,run2 python scripts/count_pharmacist_closings.py
기준(REQ-VXKQ 본문): 「약사와 상담하세요」「약사에게 문의하세요」「약사와 상의하세요」「약사에게 (먼저) 확인하세요」 꼴 —
문장 안에 의사·의료진·주치의·전문의·병원·의료기관·진료·응급실 이 함께 없을 때만 '약사만' 으로 센다.
  strict = 그 문구로 문장이 끝남(끝맺음)  ·  loose = 문장 어디에든 있음
"""
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, "/app")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import db  # noqa: E402

PHARM = re.compile(r"약사(?:님)?(?:와|과|에게|께|한테|분과|님과)?\s*(?:먼저\s*)?(상담|상의|문의|확인)")
TAIL = re.compile(r"약사(?:님)?(?:와|과|에게|께|한테|분과|님과)?\s*(?:먼저\s*)?(상담|상의|문의|확인)"
                  r"(?:을|를)?\s*(?:하세요|하십시오|해\s?주세요|해\s?보세요|하시기\s?바랍니다|받으세요|받아\s?보세요|하시고|하셔야\s?합니다|"
                  r"하는\s?것이\s?좋습니다|하시는\s?것이\s?좋습니다|해야\s?합니다|하시길\s?권합니다|권장합니다|추천합니다)?"
                  r"[\s.!?。)\]】」』*]*$")
OTHERS = re.compile(r"의사|의료진|주치의|전문의|의료기관|병원|진료|선생님|간호사|응급실|119|내과|외과|과\s?방문|과에")
SPLIT = re.compile(r"(?<=[.!?。])\s+|\n+")


def scan(text):
    strict = Counter()
    loose = Counter()
    for s in SPLIT.split(text or ""):
        s = s.strip()
        if not s or OTHERS.search(s):
            continue
        m = PHARM.search(s)
        if not m:
            continue
        loose[m.group(1)] += 1
        if TAIL.search(s):
            strict[m.group(1)] += 1
    return strict, loose


def main():
    runs = [r.strip() for r in os.environ.get("COUNT_RUNS", "").split(",") if r.strip()]
    out = {}
    for rid in runs:
        run = db.get_test_run(rid)
        if not run:
            out[rid] = {"error": "run not found"}
            continue
        res = [r for r in run.get("results") or [] if isinstance(r, dict)]
        a_strict, a_loose, s_strict, s_loose = [], [], Counter(), Counter()
        empty = mention = 0
        for r in res:
            txt = r.get("response") or ""
            if not txt:
                empty += 1
                continue
            mention += "약사" in txt
            st, lo = scan(txt)
            if lo:
                a_loose.append(r.get("scenarioId"))
                s_loose.update(lo)
            if st:
                a_strict.append(r.get("scenarioId"))
                s_strict.update(st)
        out[rid] = {"results": len(res), "empty_answers": empty, "answers_mentioning_pharmacist": mention,
                    "answers_with_pharmacist_only_closing": len(a_strict), "closing_sentences_by_verb": dict(s_strict),
                    "answers_with_pharmacist_only_anywhere": len(a_loose), "sentences_by_verb_anywhere": dict(s_loose),
                    "ids_closing": sorted(filter(None, a_strict)), "ids_anywhere": sorted(filter(None, a_loose))}
        print(f"[count] {rid} results={len(res)} empty={empty} closing={len(a_strict)} anywhere={len(a_loose)} "
              f"by_verb={dict(s_strict)}")
    print("[count] JSON " + json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
