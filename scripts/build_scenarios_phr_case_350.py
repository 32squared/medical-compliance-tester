#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PHR 문항 350건(medical-eval 인계본) → 호스트 적재 JSON.

입력: medical-eval scripts/export_host_scenarios.py 산출 scenarios_phr_case.json
      (doc-archive DOC-0649, category phr_case, 70케이스 × 5문항)
출력: scripts/scenarios_phr_case_350.json — seed_scenarios_json.py 가 읽는 형식

바꾸는 것 (값·문항 본문은 그대로):
  - phrCaseId  'CASE-nn' → 'phr_CASE-nn'  (호스트 phr_cases.id 형식. seed_phr_batch·v18 회귀와 같다)
  - tags       'case:CASE-nn' → 'case:phr_CASE-nn'
  - 케이스 번호를 운영 DB 번호로 바꾼다(scripts/phr_case_remap.json, 사람 ID 대응).
    인계본·medical-eval 은 문항 생성기 번호(시트 등장 순서)를 쓰고 운영 DB 는 seed_advisory 번호를 쓴다.
    바꾸지 않으면 350문항 중 305문항이 다른 사람의 PHR 로 답변된다(2026-09-22 확인).
    원래 번호는 tags 'srccase:CASE-nn' 로 남긴다.
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
REMAP = os.path.join(HERE, 'phr_case_remap.json')


def load_remap(path=REMAP):
    with open(path, encoding='utf-8') as f:
        return json.load(f)['remap']


def _bool(v):
    return v if isinstance(v, bool) else str(v).strip().lower() in ('1', 'true', 'yes')


def _case(v):
    v = (v or '').strip()
    return v if not v or v.startswith('phr_') else 'phr_' + v


def convert(raw, remap=None):
    items = raw['scenarios'] if isinstance(raw, dict) else raw
    remap = remap or {}
    out = []
    for s in items:
        s = dict(s)
        src = (s.get('phrCaseId') or '').strip()
        src = src[4:] if src.startswith('phr_') else src
        s['phrCaseId'] = _case(remap.get(src, src))
        tags = [t for t in (s.get('tags') or []) if not (isinstance(t, str) and t.startswith(('case:', 'srccase:')))]
        s['tags'] = ['case:' + s['phrCaseId']] + tags + ['srccase:' + src]
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
        rows = convert(json.load(f), load_remap())
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
