"""1100건 이상 완료 배치 시계열 비교 분석.

입력: data/run-*.json (덤프된 결과)
출력: data/large-runs-compare.json (PPT 생성에 사용)
"""
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict

# 분석 대상 배치 (시간 순)
RUNS = [
    {'id': 'merged-20260515-111537-6e6f0f', 'file': 'run-6e6f0f.json', 'label': '5/15 merged', 'date': '2026-05-15'},
    {'id': 'job-20260515-142828-1e71ae',    'file': 'run-1e71ae.json', 'label': '5/15',        'date': '2026-05-15'},
    {'id': 'job-20260520-094819-886cf2',    'file': 'run-886cf2.json', 'label': '5/20',        'date': '2026-05-20'},
    {'id': 'job-20260521-000816-86071f',    'file': 'run-86071f.json', 'label': '5/21',        'date': '2026-05-21'},
    {'id': 'job-20260525-074603-85b359',    'file': 'run-85b359.json', 'label': '5/25',        'date': '2026-05-25'},
    {'id': 'job-20260526-201144-24410e',    'file': 'run-24410e.json', 'label': '5/26',        'date': '2026-05-26'},
]


def analyze_single(d):
    """단일 배치 분석."""
    results = d.get('results_json') or []
    n = len(results)

    # 점수
    finals = [r.get('finalScore') for r in results if isinstance(r.get('finalScore'), (int, float))]
    consults = [(r.get('consultationEval') or {}).get('totalScore') for r in results
                if isinstance((r.get('consultationEval') or {}).get('totalScore'), (int, float))]
    grades = Counter()
    for r in results:
        g = (r.get('gptEval') or {}).get('grade')
        if g: grades[g] += 1

    consult_grades = Counter()
    for r in results:
        g = (r.get('consultationEval') or {}).get('grade')
        if g: consult_grades[g] += 1

    # 응답 길이
    lens = [r.get('responseLength', 0) for r in results if r.get('responseLength')]
    short_under_500 = sum(1 for l in lens if l < 500)
    short_under_300 = sum(1 for l in lens if l < 300)
    long_over_1000 = sum(1 for l in lens if l >= 1000)

    # 위반 통계
    total_viols = 0
    critical_v = high_v = medium_v = low_v = 0
    has_viol = 0
    by_law = Counter()
    by_type = Counter()
    for r in results:
        viols = (r.get('gptEval') or {}).get('violations') or []
        if viols:
            has_viol += 1
        for v in viols:
            if not isinstance(v, dict):
                continue
            total_viols += 1
            sev = (v.get('severity') or '').upper()
            if sev == 'CRITICAL': critical_v += 1
            elif sev == 'HIGH': high_v += 1
            elif sev == 'MEDIUM': medium_v += 1
            elif sev == 'LOW': low_v += 1
            by_law[v.get('law', '?')] += 1
            by_type[v.get('type', '?')] += 1

    # 응답 시간
    rtimes = [r.get('responseTime') for r in results
              if isinstance(r.get('responseTime'), (int, float)) and r.get('responseTime') > 0]
    ftms = [r.get('firstTokenMs') for r in results
            if isinstance(r.get('firstTokenMs'), (int, float)) and r.get('firstTokenMs') > 0]

    # 재시도
    multi_attempt = sum(1 for r in results if (r.get('attempts') or 1) > 1)

    # 4분면 (법률 ≥80, 문진 ≥70)
    gg = gp = pg = pp = 0
    for r in results:
        f = r.get('finalScore')
        c = (r.get('consultationEval') or {}).get('totalScore')
        if isinstance(f, (int, float)) and isinstance(c, (int, float)):
            if f >= 80 and c >= 70: gg += 1
            elif f >= 80: gp += 1
            elif c >= 70: pg += 1
            else: pp += 1

    # 위험도별
    risk_dist = Counter(r.get('riskLevel') for r in results)

    return {
        'total': n,
        'passed': d.get('passed', 0),
        'failed': d.get('failed', 0),
        'pass_rate': (d.get('passed', 0) / n * 100) if n else 0,
        'env': d.get('env', ''),
        'run_at': d.get('run_at', ''),

        # 점수
        'law_mean': statistics.mean(finals) if finals else 0,
        'law_median': statistics.median(finals) if finals else 0,
        'consult_mean': statistics.mean(consults) if consults else 0,
        'consult_median': statistics.median(consults) if consults else 0,
        'law_consult_gap': (statistics.mean(finals) - statistics.mean(consults)) if finals and consults else 0,
        'grades': dict(grades),
        'consult_grades': dict(consult_grades),

        # 응답 길이
        'resp_len_mean': statistics.mean(lens) if lens else 0,
        'resp_len_median': statistics.median(lens) if lens else 0,
        'short_under_500_pct': (short_under_500 / len(lens) * 100) if lens else 0,
        'short_under_300_pct': (short_under_300 / len(lens) * 100) if lens else 0,
        'long_over_1000_pct': (long_over_1000 / len(lens) * 100) if lens else 0,

        # 위반
        'total_violations': total_viols,
        'critical_violations': critical_v,
        'high_violations': high_v,
        'medium_violations': medium_v,
        'low_violations': low_v,
        'scenarios_with_violations': has_viol,
        'violation_rate': (has_viol / n * 100) if n else 0,
        'top_law': by_law.most_common(5),
        'top_type': by_type.most_common(8),

        # 응답 시간
        'response_time_mean_ms': statistics.mean(rtimes) if rtimes else 0,
        'response_time_p95_ms': statistics.quantiles(rtimes, n=20)[18] if len(rtimes) >= 20 else 0,
        'first_token_mean_ms': statistics.mean(ftms) if ftms else 0,
        'multi_attempt_count': multi_attempt,
        'multi_attempt_pct': (multi_attempt / n * 100) if n else 0,

        # 4분면
        'quad_good_good': gg,
        'quad_good_poor': gp,
        'quad_poor_good': pg,
        'quad_poor_poor': pp,

        # 위험도
        'risk_dist': dict(risk_dist),
    }


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_runs = []
    for r in RUNS:
        fp = os.path.join(base, 'data', r['file'])
        if not os.path.exists(fp):
            print(f'skip: {r["file"]} 없음', flush=True)
            continue
        print(f'분석: {r["label"]} ({r["file"]})', flush=True)
        with open(fp, 'r', encoding='utf-8') as f:
            d = json.load(f)
        info = analyze_single(d)
        info['id'] = r['id']
        info['label'] = r['label']
        info['date'] = r['date']
        out_runs.append(info)

    output = {'runs': out_runs, 'count': len(out_runs)}
    out_path = os.path.join(base, 'data', 'large-runs-compare.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\n저장: {out_path}', flush=True)

    # 콘솔 요약
    print()
    print(f'{"라벨":12s}  {"total":>5s}  {"pass%":>6s}  {"법률":>6s}  {"문진":>6s}  {"격차":>6s}  {"응답길이":>8s}  {"위반/응답":>9s}  {"CRIT":>5s}  {"이상적":>5s}')
    for r in out_runs:
        print(f'{r["label"]:12s}  {r["total"]:5d}  {r["pass_rate"]:5.1f}%  {r["law_mean"]:6.1f}  {r["consult_mean"]:6.1f}  {r["law_consult_gap"]:6.1f}  {r["resp_len_mean"]:8.0f}  {r["scenarios_with_violations"]:9d}  {r["critical_violations"]:5d}  {r["quad_good_good"]:5d}')


if __name__ == '__main__':
    main()
