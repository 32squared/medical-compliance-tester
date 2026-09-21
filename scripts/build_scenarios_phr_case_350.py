#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PHR 문항 350건(medical-eval 인계본) → 호스트 적재 JSON.

입력: medical-eval scripts/export_host_scenarios.py 산출 scenarios_phr_case.json
      (doc-archive DOC-0649, category phr_case, 70케이스 × 5문항)
출력: scripts/scenarios_phr_case_350.json — seed_scenarios_json.py 가 읽는 형식

바꾸는 것 (값·문항 본문은 그대로):
  - phrCaseId  'CASE-nn' → 'phr_CASE-nn'  (호스트 phr_cases.id 형식. seed_phr_batch·v18 회귀와 같다)
  - tags       'case:CASE-nn' → 'case:phr_CASE-nn'
  - shouldRefuse·enabled 를 bool 로 정규화, _exportMeta 는 버린다
검증: id 350종 유일, 케이스 70종, 모든 문항에 prompt·phrCaseId 있음. 어긋나면 중단.

실행: python scripts/build_scenarios_phr_case_350.py --src <scenarios_phr_case.json>
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_SRC = 'C:/Users/20002652/project/doc-archive/inbox/medical-eval_260916_host_handoff/scenarios_phr_case.json'
OUT = os.path.join(HERE, 'scenarios_phr_case_350.json')


def _bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ('1', 'true', 'yes')


def _case(v):
    v = (v or '').strip()
    return v if not v or v.startswith('phr_') else 'phr_' + v


def convert(raw):
    items = raw['scenarios'] if isinstance(raw, dict) else raw
    out = []
    for s in items:
        s = dict(s)
        s['phrCaseId'] = _case(s.get('phrCaseId'))
        s['tags'] = ['case:' + _case(t[5:]) if isinstance(t, str) and t.startswith('case:') else t
                     for t in (s.get('tags') or [])]
        s['shouldRefuse'] = _bool(s.get('shouldRefuse', False))
        s['enabled'] = _bool(s.get('enabled', True))
        out.append(s)
    return out


def check(rows):
    ids = [r['id'] for r in rows]
    cases = {r['phrCaseId'] for r in rows}
    errs = []
    if len(rows) != 350:
        errs.append(f'문항 수 {len(rows)} (기대 350)')
    if len(set(ids)) != len(ids):
        errs.append('id 중복')
    if len(cases) != 70:
        errs.append(f'케이스 {len(cases)}종 (기대 70)')
    if any(not r.get('prompt') or not r['phrCaseId'].startswith('phr_CASE-') for r in rows):
        errs.append('prompt 또는 phrCaseId 누락')
    if {r.get('category') for r in rows} != {'phr_case'}:
        errs.append('category 가 phr_case 하나가 아님')
    return errs, len(cases)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--src', default=DEFAULT_SRC)
    args = ap.parse_args()
    with open(args.src, encoding='utf-8') as f:
        rows = convert(json.load(f))
    errs, n_case = check(rows)
    if errs:
        print('[중단] ' + ' · '.join(errs))
        return 1
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump({'scenarios': rows}, f, ensure_ascii=False, indent=1)
    print(f'{len(rows)}건 · 케이스 {n_case}종 → {os.path.relpath(OUT)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
