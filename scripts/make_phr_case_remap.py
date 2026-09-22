# -*- coding: utf-8 -*-
"""문항 생성기 케이스 번호 → 운영 DB 케이스 번호 대응표를 만든다.

문항 생성기(reports/_make_phr_batch_questions.py)는 시트 등장 순서로 CASE-01~70 을 매기고,
운영 DB 시드(scripts/seed_advisory.py)는 phr_case_builder 순서로 매긴다. 같은 번호가
70개 중 61개에서 다른 사람이라, 문항이 다른 사람의 PHR 로 답변됐다(2026-09-22 확인).
두 쪽 모두 같은 엑셀의 사람 ID(num)를 쓰므로 ID 로 맞춘다. 결과에는 케이스 번호만 남긴다.

    python scripts/make_phr_case_remap.py --xlsx <phr_70.xlsx> --generator <_make_phr_batch_questions.py>
"""
import argparse
import contextlib
import importlib.util
import io
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'phr_case_remap.json')


def build_remap(xlsx, generator):
    sys.path.insert(0, HERE)
    sys.path.insert(0, os.path.dirname(HERE))
    import seed_advisory as sa
    with contextlib.redirect_stdout(io.StringIO()):
        seed = sa.build_cases(xlsx)
    spec = importlib.util.spec_from_file_location('gen', generator)
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    g.SRC = xlsx
    people = g.load_people()
    by_pid = {}
    for c in seed:
        ref = str(c.get('person_ref') or '')
        by_pid[ref.rsplit('_', 1)[-1] if '_' in ref else ref] = c['case_id']
    remap, missing = {}, []
    for p in people:
        pid = str(p['pid']).rsplit('_', 1)[-1]
        if pid in by_pid:
            remap[p['caseNo']] = by_pid[pid]
        else:
            missing.append(p['caseNo'])
    return remap, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--xlsx', required=True)
    ap.add_argument('--generator', required=True)
    a = ap.parse_args()
    remap, missing = build_remap(a.xlsx, a.generator)
    if missing or len(set(remap.values())) != len(remap):
        print(f'대응 실패: 없음 {missing}, 중복 {len(remap) - len(set(remap.values()))}')
        return 3
    json.dump({'note': '문항 생성기 CASE 번호 → 운영 DB(seed_advisory) CASE 번호. 사람 ID 로 대응',
               'remap': remap}, open(OUT, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    moved = sum(1 for k, v in remap.items() if k != v)
    print(f'{len(remap)}건 대응, 번호가 바뀌는 케이스 {moved}건 → {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
