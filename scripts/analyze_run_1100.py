"""기존 시나리오 1100건 배치 결과 분석 — run-1e71ae.json 입력 → 통계 출력.

별도 HTML 보고서 생성 스크립트가 본 모듈을 import 해 결과를 가져간다.
"""
import json
import os
import statistics
import sys
from collections import Counter, defaultdict


def load_run(path):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze(run):
    results = run.get('results_json') or []
    total = len(results)

    out = {
        'meta': {
            'id': run.get('id'),
            'run_at': run.get('run_at'),
            'env': run.get('env'),
            'tester': run.get('tester'),
            'status': run.get('status'),
            'total': run.get('total') or total,
            'passed': run.get('passed') or 0,
            'failed': run.get('failed') or 0,
        }
    }

    # 1. 점수 분포
    scores = [float(r.get('finalScore') or 0) for r in results]
    out['score'] = {
        'mean': statistics.mean(scores) if scores else 0,
        'median': statistics.median(scores) if scores else 0,
        'stdev': statistics.stdev(scores) if len(scores) > 1 else 0,
        'min': min(scores) if scores else 0,
        'max': max(scores) if scores else 0,
        'p25': statistics.quantiles(scores, n=4)[0] if len(scores) >= 4 else 0,
        'p75': statistics.quantiles(scores, n=4)[2] if len(scores) >= 4 else 0,
        'zero_count': sum(1 for s in scores if s == 0),
        'perfect_count': sum(1 for s in scores if s == 100),
        'below_60': sum(1 for s in scores if s < 60),
        'over_80': sum(1 for s in scores if s >= 80),
    }

    # 10점 단위 히스토그램
    hist = [0] * 11  # 0-9, 10-19, ..., 100
    for s in scores:
        b = min(int(s // 10), 10)
        hist[b] += 1
    out['histogram'] = hist

    # 2. 등급 분포 (gptEval.grade)
    grade_counter = Counter()
    for r in results:
        g = (r.get('gptEval') or {}).get('grade') or 'NA'
        grade_counter[g] += 1
    out['grades'] = dict(grade_counter)

    # 3. 카테고리별 통계
    cat_stats = defaultdict(lambda: {'total': 0, 'passed': 0, 'failed': 0, 'scores': []})
    for r in results:
        cat = r.get('category') or 'unknown'
        st = cat_stats[cat]
        st['total'] += 1
        if r.get('status') == 'pass':
            st['passed'] += 1
        else:
            st['failed'] += 1
        st['scores'].append(float(r.get('finalScore') or 0))
    cats = {}
    for cat, st in cat_stats.items():
        cats[cat] = {
            'total': st['total'],
            'passed': st['passed'],
            'failed': st['failed'],
            'pass_rate': (st['passed'] / st['total'] * 100) if st['total'] else 0,
            'mean_score': statistics.mean(st['scores']) if st['scores'] else 0,
            'median_score': statistics.median(st['scores']) if st['scores'] else 0,
        }
    out['categories'] = cats

    # 4. risk level 분포
    risk_counter = Counter()
    risk_pass = defaultdict(lambda: {'pass': 0, 'fail': 0})
    for r in results:
        risk = r.get('riskLevel') or 'UNKNOWN'
        risk_counter[risk] += 1
        if r.get('status') == 'pass':
            risk_pass[risk]['pass'] += 1
        else:
            risk_pass[risk]['fail'] += 1
    out['risk_level'] = {
        'counts': dict(risk_counter),
        'pass_rate': {k: (v['pass'] / (v['pass'] + v['fail']) * 100) if (v['pass'] + v['fail']) else 0
                      for k, v in risk_pass.items()},
    }

    # 5. 위반 패턴 — gptEval.violations
    violation_counter = Counter()
    violation_examples = defaultdict(list)
    for r in results:
        viols = (r.get('gptEval') or {}).get('violations') or []
        for v in viols:
            if isinstance(v, dict):
                key = v.get('rule') or v.get('type') or v.get('description') or str(v)[:80]
            else:
                key = str(v)[:80]
            violation_counter[key] += 1
            if len(violation_examples[key]) < 3:
                violation_examples[key].append(r.get('scenarioId', '?'))
    out['violations'] = {
        'top': violation_counter.most_common(15),
        'examples': {k: violation_examples[k] for k, _ in violation_counter.most_common(15)},
        'total_unique': len(violation_counter),
    }

    # 6. consultationEval — 5축 평균 점수
    axes_keys = set()
    for r in results:
        ce = r.get('consultationEval') or {}
        for k in (ce.get('axes') or {}).keys():
            axes_keys.add(k)
    axes_scores = {k: [] for k in axes_keys}
    for r in results:
        ce = r.get('consultationEval') or {}
        ax = ce.get('axes') or {}
        for k in axes_keys:
            v = ax.get(k)
            if isinstance(v, dict):
                s = v.get('score')
            else:
                s = v
            if isinstance(s, (int, float)):
                axes_scores[k].append(float(s))
    out['consultation_axes'] = {}
    for k, vals in axes_scores.items():
        if vals:
            out['consultation_axes'][k] = {
                'mean': statistics.mean(vals),
                'median': statistics.median(vals),
                'min': min(vals),
                'max': max(vals),
                'n': len(vals),
            }

    # 7. 하위/상위 시나리오 샘플
    sorted_by_score = sorted(results, key=lambda r: float(r.get('finalScore') or 0))
    bottom = sorted_by_score[:10]
    top = sorted_by_score[-5:]
    out['bottom_scenarios'] = [
        {
            'scenarioId': r.get('scenarioId'),
            'category': r.get('category'),
            'subcategory': r.get('subcategory'),
            'score': r.get('finalScore'),
            'grade': (r.get('gptEval') or {}).get('grade'),
            'gptSummary': (r.get('gptEval') or {}).get('summary', '')[:200],
            'violations': [
                (v.get('rule') or v.get('description') or str(v))[:100] if isinstance(v, dict) else str(v)[:100]
                for v in ((r.get('gptEval') or {}).get('violations') or [])[:3]
            ],
        }
        for r in bottom
    ]
    out['top_scenarios'] = [
        {
            'scenarioId': r.get('scenarioId'),
            'category': r.get('category'),
            'subcategory': r.get('subcategory'),
            'score': r.get('finalScore'),
            'grade': (r.get('gptEval') or {}).get('grade'),
        }
        for r in top
    ]

    # 8. 응답 시간 통계 (responseTime in ms)
    rtimes = [r.get('responseTime') for r in results if isinstance(r.get('responseTime'), (int, float)) and r.get('responseTime') > 0]
    if rtimes:
        out['response_time'] = {
            'mean': statistics.mean(rtimes),
            'median': statistics.median(rtimes),
            'p25': statistics.quantiles(rtimes, n=4)[0] if len(rtimes) >= 4 else 0,
            'p75': statistics.quantiles(rtimes, n=4)[2] if len(rtimes) >= 4 else 0,
            'p95': statistics.quantiles(rtimes, n=20)[18] if len(rtimes) >= 20 else 0,
            'min': min(rtimes),
            'max': max(rtimes),
        }
    else:
        out['response_time'] = {}

    # 9. subcategory 별 통계 (상위 N개만)
    sub_stats = defaultdict(lambda: {'total': 0, 'passed': 0, 'scores': []})
    for r in results:
        sub = r.get('subcategory') or 'unknown'
        sub_stats[sub]['total'] += 1
        if r.get('status') == 'pass':
            sub_stats[sub]['passed'] += 1
        sub_stats[sub]['scores'].append(float(r.get('finalScore') or 0))
    subs = []
    for sub, st in sub_stats.items():
        subs.append({
            'name': sub,
            'total': st['total'],
            'passed': st['passed'],
            'pass_rate': (st['passed'] / st['total'] * 100) if st['total'] else 0,
            'mean_score': statistics.mean(st['scores']) if st['scores'] else 0,
        })
    # 평균 점수 낮은 것이 우선순위 — 모수가 충분한 것만 (3개 이상)
    subs_sorted = sorted([s for s in subs if s['total'] >= 3], key=lambda s: s['mean_score'])
    out['subcategories_worst'] = subs_sorted[:15]
    out['subcategories_best'] = sorted([s for s in subs if s['total'] >= 3], key=lambda s: -s['mean_score'])[:10]

    # 10. fail 사유 분류 — finalSource 별 분포 (gpt vs regex)
    src_counter = Counter()
    for r in results:
        src_counter[r.get('finalSource') or 'unknown'] += 1
    out['final_source'] = dict(src_counter)

    # gptEval grade 가 D/F 인 시나리오들의 위반 패턴
    fail_grades_violations = Counter()
    for r in results:
        ge = r.get('gptEval') or {}
        if ge.get('grade') in ('D', 'F'):
            for v in (ge.get('violations') or []):
                if isinstance(v, dict):
                    key = v.get('rule') or v.get('type') or v.get('description') or str(v)[:80]
                else:
                    key = str(v)[:80]
                fail_grades_violations[key] += 1
    out['fail_violations'] = fail_grades_violations.most_common(10)

    return out


def print_report(out):
    m = out['meta']
    print(f'\n{"="*60}')
    print(f'배치: {m["id"]}')
    print(f'실행: {m["run_at"]}  env={m["env"]}  status={m["status"]}')
    print(f'총 {m["total"]}건  pass={m["passed"]}  fail={m["failed"]}  pass_rate={m["passed"]/m["total"]*100:.1f}%')
    print('='*60)

    s = out['score']
    print(f'\n[점수 분포]')
    print(f'  mean={s["mean"]:.1f}  median={s["median"]:.1f}  stdev={s["stdev"]:.1f}')
    print(f'  min={s["min"]:.0f}  p25={s["p25"]:.1f}  p75={s["p75"]:.1f}  max={s["max"]:.0f}')
    print(f'  0점={s["zero_count"]}건  100점={s["perfect_count"]}건  <60={s["below_60"]}건  ≥80={s["over_80"]}건')

    print(f'\n[히스토그램 10점 단위]')
    for i, n in enumerate(out['histogram']):
        label = f'{i*10}-{i*10+9}' if i < 10 else '100'
        bar = '█' * int(n / max(out['histogram']) * 40) if max(out['histogram']) > 0 else ''
        print(f'  {label:>6s}: {n:4d}  {bar}')

    print(f'\n[GPT 등급]')
    for g in ['A', 'B', 'C', 'D', 'F', 'NA']:
        n = out['grades'].get(g, 0)
        print(f'  {g}: {n:4d} ({n/m["total"]*100:.1f}%)')

    print(f'\n[카테고리별]')
    cats = sorted(out['categories'].items(), key=lambda kv: -kv[1]['total'])
    for cat, st in cats:
        print(f'  {cat:25s}  {st["total"]:4d}건  pass={st["pass_rate"]:5.1f}%  mean={st["mean_score"]:.1f}')

    print(f'\n[위험도 분포]')
    for risk, n in sorted(out['risk_level']['counts'].items(), key=lambda kv: -kv[1]):
        pr = out['risk_level']['pass_rate'].get(risk, 0)
        print(f'  {risk:10s}  {n:4d}  pass_rate={pr:.1f}%')

    print(f'\n[Top 위반 패턴 (전체)]')
    for rule, n in out['violations']['top'][:10]:
        ex = ', '.join(out['violations']['examples'].get(rule, [])[:2])
        print(f'  [{n:4d}회]  {rule[:60]}  예: {ex}')

    print(f'\n[D/F 등급 위반 패턴]')
    for rule, n in out['fail_violations'][:10]:
        print(f'  [{n:4d}회]  {rule[:80]}')

    print(f'\n[Consultation 평가 5축]')
    for k, v in out['consultation_axes'].items():
        print(f'  {k:25s}  mean={v["mean"]:5.1f}  median={v["median"]:5.1f}  n={v["n"]}')

    if out['response_time']:
        rt = out['response_time']
        print(f'\n[응답시간 (ms)]')
        print(f'  mean={rt["mean"]:.0f}  median={rt["median"]:.0f}  p95={rt["p95"]:.0f}  max={rt["max"]:.0f}')

    print(f'\n[성과 낮은 subcategory Top 10]')
    for s in out['subcategories_worst'][:10]:
        print(f'  {s["name"][:40]:40s}  n={s["total"]:3d}  mean={s["mean_score"]:5.1f}  pass={s["pass_rate"]:5.1f}%')

    print(f'\n[하위 점수 시나리오 Top 10]')
    for r in out['bottom_scenarios']:
        print(f'  {r["scenarioId"]:15s}  score={r["score"]:5.1f}  grade={r["grade"]}  cat={r["category"]}')


if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else 'data/run-1e71ae.json'
    run = load_run(path)
    out = analyze(run)

    print_report(out)

    # JSON 으로도 저장 (HTML 생성 스크립트가 사용)
    json_out = sys.argv[2] if len(sys.argv) > 2 else 'data/run-1e71ae-analysis.json'
    with open(json_out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'\n분석 결과 저장: {json_out}')
