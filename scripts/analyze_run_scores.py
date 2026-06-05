"""HB batch 결과의 점수 분포를 theme / axis / score-bucket 별로 집계.

리포트 endpoint (`/api/history/<runId>/healthbench-report`) 가 이미 비슷한 집계를
하지만 본 스크립트는 CLI 에서 빠르게 보기 + 여러 run 비교 + score histogram 추가.

사용:
  ANALYZE_RUN_ID=hb-full-100-... python scripts/analyze_run_scores.py
  ANALYZE_RUN_ID=hb-full-... python scripts/analyze_run_scores.py --histogram
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db


def _bucket(s):
    if s is None: return 'no-score'
    if s >= 75: return '75-100 (우수)'
    if s >= 50: return '50-74 (통과)'
    if s >= 25: return '25-49 (미흡)'
    return '0-24 (심각)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--histogram', action='store_true', help='10점 단위 막대 그래프 추가')
    ap.add_argument('--show-worst', type=int, default=5, help='최저 점수 시나리오 N개 표시')
    args = ap.parse_args()

    run_id = os.environ.get('ANALYZE_RUN_ID', '').strip()
    if not run_id:
        raise SystemExit('ANALYZE_RUN_ID env var 필요')

    print(f'=== analyze_run_scores: {run_id} ===', flush=True)

    r = db.get_test_run(run_id)
    if not r:
        raise SystemExit(f'run 없음: {run_id}')

    raw = r.get('results') or r.get('results_json')
    if isinstance(raw, str):
        results = json.loads(raw)
    elif isinstance(raw, list):
        results = raw
    else:
        results = []

    hb = [x for x in results if (x.get('scenarioId') or '').startswith('HB-')]
    print(f'전체 결과: {len(results)}건  HB-*: {len(hb)}건', flush=True)
    print('', flush=True)

    # 1. score bucket 분포
    print('## 1. Score Bucket 분포 (rubric score)', flush=True)
    scores = [x.get('rubricEval', {}).get('score') for x in hb]
    bucket_counts = Counter(_bucket(s) for s in scores)
    for b in ['75-100 (우수)', '50-74 (통과)', '25-49 (미흡)', '0-24 (심각)', 'no-score']:
        n = bucket_counts.get(b, 0)
        pct = (n / len(hb) * 100) if hb else 0
        print(f'  {b:18s}  {n:4d}건  {"█" * int(pct/2):20s}  {pct:.1f}%', flush=True)
    print('', flush=True)

    # 2. histogram (10점 단위)
    if args.histogram:
        print('## 2. 10점 단위 histogram', flush=True)
        bins = [0] * 11
        for s in scores:
            if s is None: continue
            idx = min(10, max(0, int(s // 10)))
            bins[idx] += 1
        max_n = max(bins) if bins else 1
        for i, n in enumerate(bins):
            label = f'{i*10:3d}-{i*10+9 if i<10 else 100}'
            bar = '█' * int(n / max_n * 30) if max_n > 0 else ''
            print(f'  {label}: {n:4d} {bar}', flush=True)
        print('', flush=True)

    # 3. 통계
    valid_scores = [s for s in scores if s is not None]
    if valid_scores:
        print('## 3. 통계', flush=True)
        print(f'  평균:    {sum(valid_scores)/len(valid_scores):.2f}', flush=True)
        sorted_s = sorted(valid_scores)
        print(f'  median:  {sorted_s[len(sorted_s)//2]:.2f}', flush=True)
        print(f'  min:     {min(valid_scores):.2f}', flush=True)
        print(f'  max:     {max(valid_scores):.2f}', flush=True)
        passed = sum(1 for s in valid_scores if s >= 50)
        print(f'  통과율 (≥50): {passed}/{len(valid_scores)} ({passed/len(valid_scores)*100:.1f}%)', flush=True)
        print('', flush=True)

    # 4. theme 별 평균
    print('## 4. Theme 별 평균 점수', flush=True)
    by_theme = defaultdict(list)
    for x in hb:
        theme = x.get('subcategory') or 'unknown'
        s = x.get('rubricEval', {}).get('score')
        if s is not None:
            by_theme[theme].append(s)
    rows = sorted(by_theme.items(), key=lambda kv: -sum(kv[1])/len(kv[1]) if kv[1] else 0)
    for theme, sc in rows:
        avg = sum(sc) / len(sc) if sc else 0
        pass_n = sum(1 for s in sc if s >= 50)
        print(f'  {theme:25s}  n={len(sc):4d}  avg={avg:6.2f}  pass={pass_n:4d} ({pass_n/len(sc)*100 if sc else 0:.1f}%)', flush=True)
    print('', flush=True)

    # 5. axis 별 평균
    print('## 5. Axis 별 가중점수', flush=True)
    axis_awarded = defaultdict(float)
    axis_possible = defaultdict(float)
    axis_met = defaultdict(int)
    axis_total = defaultdict(int)
    for x in hb:
        items = (x.get('rubricEval') or {}).get('items') or []
        for it in items:
            tags = it.get('tags') or []
            pts = float(it.get('points', 0) or 0)
            met = bool(it.get('met'))
            for tag in tags:
                if not isinstance(tag, str): continue
                if tag.startswith('axis:'):
                    ax = tag[len('axis:'):]
                    axis_total[ax] += 1
                    if pts > 0: axis_possible[ax] += pts
                    if met:
                        axis_met[ax] += 1
                        if pts > 0: axis_awarded[ax] += pts
    if axis_total:
        rows = sorted(axis_total.items(), key=lambda kv: -kv[1])
        for ax, total in rows:
            possible = axis_possible[ax]
            awarded = axis_awarded[ax]
            met_n = axis_met[ax]
            weighted = (awarded / possible * 100) if possible > 0 else 0
            print(f'  {ax:25s}  items={total:5d}  met={met_n:4d}/{total}  pts={awarded:6.1f}/{possible:6.1f}  weighted={weighted:6.2f}', flush=True)
    print('', flush=True)

    # 6. 최저 점수 시나리오
    print(f'## 6. 최저 점수 시나리오 (worst {args.show_worst})', flush=True)
    sorted_results = sorted(hb, key=lambda x: x.get('rubricEval', {}).get('score') if x.get('rubricEval', {}).get('score') is not None else 999)
    for x in sorted_results[:args.show_worst]:
        sid = x.get('scenarioId', '?')
        re = x.get('rubricEval') or {}
        sc = re.get('score')
        met = re.get('metCount')
        total = re.get('totalCount')
        theme = x.get('subcategory') or '?'
        print(f'  {sid:15s}  score={str(sc):6s}  met={met}/{total}  theme={theme}', flush=True)


if __name__ == '__main__':
    main()
