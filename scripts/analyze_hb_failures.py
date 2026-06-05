"""HB batch 결과의 실패/약점 패턴 심층 분석.

대상: 0점 / 저점 시나리오 + 음수 rubric 항목 발생 패턴 + theme × axis 교차표 +
가장 자주 놓치는 양수 항목 top N.

사용:
  ANALYZE_RUN_ID=job-... python scripts/analyze_hb_failures.py
  ANALYZE_RUN_ID=job-... python scripts/analyze_hb_failures.py --top 20
"""
import argparse
import json
import os
import re
import sys
from collections import Counter, defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import db


def _normalize_criterion(text):
    """비슷한 criterion 묶기 위해 정규화 — 숫자/약품명 등 변동 부분 제거 효과."""
    if not text:
        return ''
    t = text.lower().strip()
    t = re.sub(r'\s+', ' ', t)
    # 너무 긴 criterion 은 앞부분만
    if len(t) > 120:
        t = t[:120] + '...'
    return t


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--top', type=int, default=15, help='top N criterion 표시')
    args = ap.parse_args()

    run_id = os.environ.get('ANALYZE_RUN_ID', '').strip()
    if not run_id:
        raise SystemExit('ANALYZE_RUN_ID env var 필요')

    print(f'=== analyze_hb_failures: {run_id} ===', flush=True)
    r = db.get_test_run(run_id)
    if not r:
        raise SystemExit(f'run 없음: {run_id}')

    raw = r.get('results') or r.get('results_json')
    if isinstance(raw, str):
        results = json.loads(raw)
    else:
        results = raw or []
    hb = [x for x in results if (x.get('scenarioId') or '').startswith('HB-')]
    print(f'HB 결과: {len(hb)}건', flush=True)
    print('', flush=True)

    # ─────────────────────────────────────────────
    # 1. 음수 rubric 항목 발생 (부정 행동 met)
    # ─────────────────────────────────────────────
    print('## 1. 음수 rubric 항목 met (부정 행동 발생) — 가장 흔한 패턴', flush=True)
    print('   (criterion + 점수 + axis tag, 발생 횟수 순)', flush=True)
    neg_met_counter = Counter()  # (criterion_norm, points, axis_tag) -> count
    neg_met_examples = defaultdict(list)  # 동일 패턴의 시나리오 ID 샘플
    for x in hb:
        items = (x.get('rubricEval') or {}).get('items') or []
        for it in items:
            pts = float(it.get('points', 0) or 0)
            if pts >= 0:
                continue
            if not bool(it.get('met')):
                continue
            crit = _normalize_criterion(it.get('criterion', ''))
            # 가장 의미있는 axis 1개 추출
            tags = it.get('tags') or []
            axis = next((t[len('axis:'):] for t in tags if isinstance(t, str) and t.startswith('axis:')), '')
            key = (crit, pts, axis)
            neg_met_counter[key] += 1
            if len(neg_met_examples[key]) < 3:
                neg_met_examples[key].append(x.get('scenarioId', '?'))

    top_neg = neg_met_counter.most_common(args.top)
    if not top_neg:
        print('  (음수 항목 met 사례 없음)', flush=True)
    else:
        for (crit, pts, axis), n in top_neg:
            samples = ', '.join(neg_met_examples[(crit, pts, axis)])
            print(f'  [{n:4d}회] ({pts:+g} pt, axis:{axis})  {crit[:100]}', flush=True)
            print(f'         예: {samples}', flush=True)
    print('', flush=True)

    # ─────────────────────────────────────────────
    # 2. 가장 자주 놓치는 양수 항목 (HIGH-VALUE missed)
    # ─────────────────────────────────────────────
    print('## 2. 가장 자주 놓친 양수 항목 (positive points, not met)', flush=True)
    print('   (points 가 높고 자주 놓친 항목 우선 — 점수 영향 가장 큰 약점)', flush=True)
    missed_counter = Counter()
    missed_examples = defaultdict(list)
    missed_pts_lost = defaultdict(float)
    for x in hb:
        items = (x.get('rubricEval') or {}).get('items') or []
        for it in items:
            pts = float(it.get('points', 0) or 0)
            if pts <= 0:
                continue
            if bool(it.get('met')):
                continue
            crit = _normalize_criterion(it.get('criterion', ''))
            tags = it.get('tags') or []
            axis = next((t[len('axis:'):] for t in tags if isinstance(t, str) and t.startswith('axis:')), '')
            key = (crit, pts, axis)
            missed_counter[key] += 1
            missed_pts_lost[key] += pts
            if len(missed_examples[key]) < 3:
                missed_examples[key].append(x.get('scenarioId', '?'))

    # 손실 점수 (count × points) 순 정렬
    top_missed = sorted(missed_counter.items(), key=lambda kv: -missed_pts_lost[kv[0]])[:args.top]
    for (crit, pts, axis), n in top_missed:
        lost = missed_pts_lost[(crit, pts, axis)]
        samples = ', '.join(missed_examples[(crit, pts, axis)][:2])
        print(f'  [{n:4d}회 × {pts:+g}pt = {lost:6.0f}pt 손실] (axis:{axis})  {crit[:100]}', flush=True)
        print(f'         예: {samples}', flush=True)
    print('', flush=True)

    # ─────────────────────────────────────────────
    # 3. Theme × Axis 가중점수 cross-table
    # ─────────────────────────────────────────────
    print('## 3. Theme × Axis 가중점수 cross-table', flush=True)
    cross_possible = defaultdict(lambda: defaultdict(float))
    cross_awarded = defaultdict(lambda: defaultdict(float))
    for x in hb:
        theme = x.get('subcategory') or 'unknown'
        items = (x.get('rubricEval') or {}).get('items') or []
        for it in items:
            tags = it.get('tags') or []
            pts = float(it.get('points', 0) or 0)
            met = bool(it.get('met'))
            for tag in tags:
                if not isinstance(tag, str) or not tag.startswith('axis:'):
                    continue
                ax = tag[len('axis:'):]
                if pts > 0:
                    cross_possible[theme][ax] += pts
                if met:
                    cross_awarded[theme][ax] += pts

    # axis 목록
    all_axes = sorted({ax for t in cross_possible for ax in cross_possible[t]})
    themes = sorted(cross_possible.keys())

    if all_axes and themes:
        # 헤더
        header = '  theme                     ' + ' '.join(f'{ax[:13]:>13s}' for ax in all_axes)
        print(header, flush=True)
        print('  ' + '-' * (len(header) - 2), flush=True)
        for theme in themes:
            cells = []
            for ax in all_axes:
                possible = cross_possible[theme].get(ax, 0)
                awarded = cross_awarded[theme].get(ax, 0)
                if possible <= 0:
                    cells.append(f'{"---":>13s}')
                else:
                    weighted = (awarded / possible * 100)
                    cells.append(f'{weighted:>12.1f}%')
            print(f'  {theme:25s} ' + ' '.join(cells), flush=True)
    print('', flush=True)

    # ─────────────────────────────────────────────
    # 4. 0점 시나리오 (음수 met 또는 거의 모두 missed) 패턴
    # ─────────────────────────────────────────────
    zero_score_count = sum(1 for x in hb if (x.get('rubricEval') or {}).get('score') == 0)
    print(f'## 4. 0점 시나리오 분석 — 총 {zero_score_count}건', flush=True)

    # 0점 이유 분류
    cause_neg_only = 0  # 음수 항목 met (부정 행동 발생)
    cause_all_missed = 0  # 모든 양수 항목 missed
    cause_mixed = 0  # 음수 met + 양수 일부 missed (혼합)
    cause_low = 0  # 양수 일부 met 했지만 awarded 0 이하 (음수 영향)

    for x in hb:
        re_data = x.get('rubricEval') or {}
        if re_data.get('score') != 0:
            continue
        items = re_data.get('items') or []
        neg_met = sum(1 for it in items if (it.get('points', 0) or 0) < 0 and it.get('met'))
        pos_missed = sum(1 for it in items if (it.get('points', 0) or 0) > 0 and not it.get('met'))
        pos_met = sum(1 for it in items if (it.get('points', 0) or 0) > 0 and it.get('met'))
        if neg_met > 0 and pos_met == 0:
            cause_neg_only += 1
        elif neg_met > 0 and pos_met > 0:
            cause_low += 1
        elif neg_met == 0 and pos_met == 0:
            cause_all_missed += 1
        else:
            cause_mixed += 1
    print(f'  - 음수 met 있고 양수 met 없음:  {cause_neg_only}건  (가장 명백한 위반)', flush=True)
    print(f'  - 음수 met + 양수 met (clamp): {cause_low}건  (좋은 점도 했지만 음수 페널티로 0)', flush=True)
    print(f'  - 음수 met 없고 양수 모두 missed: {cause_all_missed}건  (필수 정보 누락)', flush=True)
    print(f'  - 혼합:                         {cause_mixed}건', flush=True)
    print('', flush=True)

    # ─────────────────────────────────────────────
    # 5. 100점 시나리오 (성공 패턴) — 어느 theme, 평균 rubric 수
    # ─────────────────────────────────────────────
    print('## 5. 100점 시나리오 분석 (성공 패턴)', flush=True)
    perfect = [x for x in hb if (x.get('rubricEval') or {}).get('score') == 100.0]
    print(f'  총 {len(perfect)}건', flush=True)
    by_theme_perfect = Counter(x.get('subcategory') or 'unknown' for x in perfect)
    for theme, n in by_theme_perfect.most_common():
        all_in_theme = sum(1 for x in hb if x.get('subcategory') == theme)
        pct = (n / all_in_theme * 100) if all_in_theme else 0
        print(f'  {theme:25s}  {n:3d}건 / {all_in_theme} ({pct:.1f}%)', flush=True)
    print('', flush=True)

    # 100점 시나리오의 평균 rubric item 수 vs 전체
    if perfect:
        avg_rubric_perfect = sum(len((x.get('rubricEval') or {}).get('items') or []) for x in perfect) / len(perfect)
        avg_rubric_all = sum(len((x.get('rubricEval') or {}).get('items') or []) for x in hb) / len(hb)
        print(f'  100점 시나리오 평균 rubric items: {avg_rubric_perfect:.1f}', flush=True)
        print(f'  전체 평균: {avg_rubric_all:.1f}', flush=True)
        diff = avg_rubric_perfect - avg_rubric_all
        if diff < -2:
            print(f'  → 100점 시나리오는 rubric 항목이 평균보다 적음 ({diff:.1f}). 적은 항목이라 만점 쉬움.', flush=True)


if __name__ == '__main__':
    main()
