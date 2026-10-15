# -*- coding: utf-8 -*-
"""mhc-viz 블록 형식 검사 CLI.

    python scripts/mhc_viz_check.py answer.md            # 답변 파일 하나
    python scripts/mhc_viz_check.py run.json --field response   # 이력 덤프(results[] 또는 list) 전부
    type answer.md | python scripts/mhc_viz_check.py -    # 표준입력
옵션 --json : 결과를 JSON 으로. 종료 코드 = 형식 위반 답변 수.
규약: docs/mhc_viz_convention_v1_20261014.html. 검사 규칙은 mhc_viz.py(호스트와 공용).
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.stdout.reconfigure(encoding='utf-8')
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import mhc_viz  # noqa: E402


def load_answers(path, field):
    if path == '-':
        return [('stdin', sys.stdin.read())]
    with open(path, encoding='utf-8') as f:
        raw = f.read()
    if path.lower().endswith('.json'):
        data = json.loads(raw)
        rows = (data.get('results') or data.get('results_json') or []) if isinstance(data, dict) else data
        out = []
        for i, r in enumerate(rows):
            if isinstance(r, dict):
                out.append((str(r.get('scenarioId') or r.get('id') or i), r.get(field, '') or ''))
        return out
    return [(os.path.basename(path), raw)]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('path')
    ap.add_argument('--field', default='response', help='JSON 덤프에서 답변 텍스트 필드(기본 response)')
    ap.add_argument('--json', action='store_true')
    args = ap.parse_args()

    answers = load_answers(args.path, args.field)
    reports, bad = [], 0
    for name, text in answers:
        rep = mhc_viz.check_answer(text)
        rep['id'] = name
        reports.append(rep)
        if not rep['ok']:
            bad += 1
    with_blocks = sum(1 for r in reports if r['blocks'] or r['unclosed'])
    if args.json:
        print(json.dumps({'answers': len(reports), 'with_blocks': with_blocks, 'invalid': bad, 'reports': reports},
                         ensure_ascii=False, indent=1))
    else:
        for r in reports:
            if not (r['blocks'] or r['unclosed']):
                continue
            mark = '  ' if r['ok'] else '!!'
            print(f"{mark} {r['id']}: 블록 {r['blocks']}개" + (' · 미닫힘' if r['unclosed'] else ''))
            for s in r['issues']:
                print(f'     - {s}')
            for i, p in enumerate(r['per_block'], 1):
                for s in p:
                    print(f'     - 블록 {i}: {s}')
        print(f'답변 {len(reports)}건 · 블록 있는 답변 {with_blocks}건 · 형식 위반 답변 {bad}건')
    sys.exit(bad)


if __name__ == '__main__':
    main()
