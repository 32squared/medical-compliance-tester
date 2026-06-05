"""v1.0 vs v1.1.1 재평가 결과 분석.

입력: data/v111_compare.json (Cloud Run Job 산출물)
출력: 콘솔 보고서 + data/v111_compare_summary.json
"""
import json
import os
import statistics
import sys
from collections import Counter


def safe(d, k, default=0):
    v = d.get(k)
    return v if isinstance(v, (int, float)) else default


def axis_score(axes, key):
    a = (axes or {}).get(key) or {}
    s = a.get('score')
    return s if isinstance(s, (int, float)) else None


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    in_path = os.path.join(base, 'data', 'v111_compare.json')
    if not os.path.exists(in_path):
        sys.exit(f'없음: {in_path}')

    with open(in_path, 'r', encoding='utf-8') as f:
        d = json.load(f)

    results = d.get('results', [])
    if not results:
        sys.exit('빈 결과')

    # 평가 실패 제외
    valid = [r for r in results if not (r.get('v111') or {}).get('error')]
    failed = len(results) - len(valid)
    print(f'== v1.0 vs v1.1.1 재평가 비교 — 5/26 PROD 1100건 중 {len(results)}건 샘플 ==')
    print(f'   유효: {len(valid)}건  ·  평가 실패: {failed}건')
    print()

    # 총점·등급 분포
    v10_scores = [safe(r['v10'], 'totalScore') for r in valid]
    v111_scores = [safe(r['v111'], 'totalScore') for r in valid]
    v10_grades = Counter(r['v10'].get('grade', '?') for r in valid)
    v111_grades = Counter(r['v111'].get('grade', '?') for r in valid)

    print('▶ 총점 분포')
    print(f'  v1.0    : 평균 {statistics.mean(v10_scores):5.1f}  중앙값 {statistics.median(v10_scores):5.1f}  최소 {min(v10_scores):3.0f}  최대 {max(v10_scores):3.0f}')
    print(f'  v1.1.1  : 평균 {statistics.mean(v111_scores):5.1f}  중앙값 {statistics.median(v111_scores):5.1f}  최소 {min(v111_scores):3.0f}  최대 {max(v111_scores):3.0f}')
    delta_mean = statistics.mean(v111_scores) - statistics.mean(v10_scores)
    print(f'  Δ 평균  : {delta_mean:+5.1f}점')
    print()

    print('▶ 등급 분포 (v1.0 → v1.1.1)')
    for g in ['A', 'B', 'C', 'D', 'F']:
        n10 = v10_grades.get(g, 0)
        n111 = v111_grades.get(g, 0)
        pct10 = n10 / len(valid) * 100
        pct111 = n111 / len(valid) * 100
        diff = n111 - n10
        arrow = '▲' if diff > 0 else ('▼' if diff < 0 else '=')
        print(f'  {g}: {n10:3d}건 ({pct10:5.1f}%) → {n111:3d}건 ({pct111:5.1f}%)  {arrow} {diff:+d}')
    print()

    # 축별 평균
    AXES = [
        ('symptomExploration', '증상 탐색', 30, 25),
        ('redFlagScreening',   '위험 선별', 25, 25),
        ('patientContext',     '환자 맥락', 20, 20),
        ('structuredApproach', '단계적 접근', 15, 15),
        ('appropriateGuidance','적절한 안내', 10, 15),
    ]
    print('▶ 축별 평균 점수 (만점 대비 %)')
    print(f'  {"축":12s}  {"v1.0":>16s}  {"v1.1.1":>16s}  {"% 변화":>10s}')
    axis_summary = []
    for key, label, max10, max111 in AXES:
        scores10 = [s for s in (axis_score(r['v10'].get('axes'), key) for r in valid) if s is not None]
        scores111 = [s for s in (axis_score(r['v111'].get('axes'), key) for r in valid) if s is not None]
        if not scores10 or not scores111:
            continue
        m10 = statistics.mean(scores10)
        m111 = statistics.mean(scores111)
        pct10 = m10 / max10 * 100
        pct111 = m111 / max111 * 100
        pct_delta = pct111 - pct10
        arrow = '▲' if pct_delta > 0 else ('▼' if pct_delta < 0 else '=')
        print(f'  {label:8s} ({max10:2d}→{max111:2d}점)  {m10:5.1f}/{max10:2d} ({pct10:4.1f}%)  {m111:5.1f}/{max111:2d} ({pct111:4.1f}%)  {arrow} {pct_delta:+5.1f}p')
        axis_summary.append({
            'key': key, 'label': label,
            'max_v10': max10, 'max_v111': max111,
            'mean_v10': round(m10, 2), 'mean_v111': round(m111, 2),
            'pct_v10': round(pct10, 1), 'pct_v111': round(pct111, 1),
            'pct_delta': round(pct_delta, 1),
        })
    print()

    # 점수 차이 큰 케이스 (상승)
    deltas = []
    for r in valid:
        ds = safe(r['v111'], 'totalScore') - safe(r['v10'], 'totalScore')
        deltas.append((ds, r))
    deltas.sort(key=lambda x: -x[0])

    print('▶ 점수 상승 Top 5 (v1.1.1에서 더 후하게 평가됨)')
    for ds, r in deltas[:5]:
        print(f'  +{ds:3d}점  [{r.get("scenarioId","?")}] {r.get("category","")}/{r.get("subcategory","")}  '
              f'v1.0={r["v10"].get("totalScore","?")}({r["v10"].get("grade","?")}) → v1.1.1={r["v111"].get("totalScore","?")}({r["v111"].get("grade","?")})')
        sum111 = (r["v111"].get("summary") or "")[:100]
        if sum111:
            print(f'         요약: {sum111}')
    print()

    print('▶ 점수 하락 Top 5 (v1.1.1에서 더 박하게 평가됨)')
    for ds, r in deltas[-5:][::-1]:
        print(f'  {ds:+3d}점  [{r.get("scenarioId","?")}] {r.get("category","")}/{r.get("subcategory","")}  '
              f'v1.0={r["v10"].get("totalScore","?")}({r["v10"].get("grade","?")}) → v1.1.1={r["v111"].get("totalScore","?")}({r["v111"].get("grade","?")})')
        sum111 = (r["v111"].get("summary") or "")[:100]
        if sum111:
            print(f'         요약: {sum111}')
    print()

    # 적절한 안내 — 5점 추가 효과 분석
    ag_up = [r for r in valid
             if axis_score(r['v111'].get('axes'), 'appropriateGuidance') is not None
             and axis_score(r['v10'].get('axes'), 'appropriateGuidance') is not None
             and axis_score(r['v111'].get('axes'), 'appropriateGuidance') > axis_score(r['v10'].get('axes'), 'appropriateGuidance')]
    ag_down = [r for r in valid
               if axis_score(r['v111'].get('axes'), 'appropriateGuidance') is not None
               and axis_score(r['v10'].get('axes'), 'appropriateGuidance') is not None
               and axis_score(r['v111'].get('axes'), 'appropriateGuidance') < axis_score(r['v10'].get('axes'), 'appropriateGuidance')]
    print(f'▶ "적절한 안내" 축 (10→15점) 변화 — {len(valid)}건 중')
    print(f'   상승: {len(ag_up)}건  ·  하락: {len(ag_down)}건  ·  동일: {len(valid)-len(ag_up)-len(ag_down)}건')
    print()

    # 위반/누락 빈도 변화 — v1.1.1 missingItems Top
    miss_v10 = Counter()
    miss_v111 = Counter()
    for r in valid:
        for it in (r['v10'].get('missingItems') or [])[:5]:
            miss_v10[it] += 1
        for it in (r['v111'].get('missingItems') or [])[:5]:
            miss_v111[it] += 1
    print('▶ 자주 누락된 항목 Top 10 (v1.1.1)')
    for item, n in miss_v111.most_common(10):
        print(f'  {n:3d}회  {item[:80]}')
    print()

    # 저장
    out = {
        'sampleSize': len(valid),
        'failed': failed,
        'totalScore': {
            'v10':  {'mean': round(statistics.mean(v10_scores), 2),  'median': statistics.median(v10_scores)},
            'v111': {'mean': round(statistics.mean(v111_scores), 2), 'median': statistics.median(v111_scores)},
            'delta_mean': round(delta_mean, 2),
        },
        'grades': {
            'v10':  dict(v10_grades),
            'v111': dict(v111_grades),
        },
        'axes': axis_summary,
        'topUp':   [{'scenarioId': r.get('scenarioId'), 'delta': ds, 'v10': r['v10'].get('totalScore'), 'v111': r['v111'].get('totalScore'), 'category': r.get('category'), 'subcategory': r.get('subcategory')} for ds, r in deltas[:5]],
        'topDown': [{'scenarioId': r.get('scenarioId'), 'delta': ds, 'v10': r['v10'].get('totalScore'), 'v111': r['v111'].get('totalScore'), 'category': r.get('category'), 'subcategory': r.get('subcategory')} for ds, r in deltas[-5:][::-1]],
        'appropriateGuidanceChange': {'up': len(ag_up), 'down': len(ag_down)},
        'topMissingV111': miss_v111.most_common(15),
    }
    out_path = os.path.join(base, 'data', 'v111_compare_summary.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'✓ 저장: {out_path}')


if __name__ == '__main__':
    main()
