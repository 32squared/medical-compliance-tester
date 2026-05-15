"""5개 batch 통합 LLM 재평가 결과 분석."""
import io, os, sys, json
from datetime import datetime
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)

import requests

PROD_URL = 'https://medical-compliance-tester-cbtevhmzrq-du.a.run.app'
RUN_IDS = [
    'batch-20260514-175526-0ae23b',
    'batch-20260514-213809-e490cd',
    'batch-20260514-222243-6560d9',
    'batch-20260514-222443-95d155',
    'batch-20260514-233533-dfcaef',
]


def main():
    admin_pw = os.environ.get('ADMIN_PW', '')
    s = requests.Session()
    s.post(f"{PROD_URL}/api/auth/login",
           json={'id': 'admin', 'password': admin_pw}, timeout=15)

    unique_seen = {}
    grade_counts = Counter()
    by_category = defaultdict(lambda: {'total': 0, 'pass': 0, 'fail': 0})
    by_risk = defaultdict(lambda: {'total': 0, 'pass': 0, 'fail': 0})
    by_source = Counter()
    no_response = 0
    no_gpt = 0

    for run_id in RUN_IDS:
        r = s.get(f"{PROD_URL}/api/history/{run_id}", timeout=60)
        if r.status_code != 200:
            continue
        j = r.json()
        for res in j.get('results', []):
            sid = res.get('scenarioId')
            if not sid or sid in unique_seen:
                continue
            unique_seen[sid] = True

            cat = res.get('category', '미분류')
            risk = res.get('riskLevel', 'UNKNOWN')
            src = res.get('source', 'manual')
            by_source[src] += 1
            by_category[cat]['total'] += 1
            by_risk[risk]['total'] += 1

            if not res.get('response'):
                no_response += 1
                continue
            gpt = res.get('gptEval')
            if not gpt or not gpt.get('grade'):
                no_gpt += 1
                continue

            grade = gpt.get('grade')
            passed = gpt.get('passed')
            grade_counts[grade] += 1

            if passed:
                by_category[cat]['pass'] += 1
                by_risk[risk]['pass'] += 1
            else:
                by_category[cat]['fail'] += 1
                by_risk[risk]['fail'] += 1

    total = len(unique_seen)
    evaluated = total - no_response - no_gpt
    total_pass = sum(c['pass'] for c in by_category.values())
    total_fail = sum(c['fail'] for c in by_category.values())

    print("=" * 70)
    print(f"  1100건 LLM-only 통합 결과 ({datetime.now().strftime('%Y-%m-%d %H:%M')})")
    print("=" * 70)
    print(f"전체 unique 시나리오: {total}")
    print(f"LLM 평가 완료: {evaluated}")
    print(f"응답 없음: {no_response}")
    print(f"LLM 평가 누락: {no_gpt}")
    print()
    print(f"통과율: {total_pass}/{evaluated} ({total_pass/evaluated*100:.1f}%)")
    print(f"실패: {total_fail}/{evaluated} ({total_fail/evaluated*100:.1f}%)")
    print()
    print("등급 분포:")
    for g in ['A', 'B', 'C', 'D', 'F']:
        c = grade_counts.get(g, 0)
        pct = c / evaluated * 100 if evaluated else 0
        print(f"  {g}: {c:4d} ({pct:5.1f}%)")
    print()
    print("Source별:")
    for src, n in by_source.most_common():
        print(f"  {src:12s}: {n}")
    print()
    print("리스크별 통과율:")
    for risk in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN']:
        d = by_risk.get(risk)
        if not d or d['total'] == 0:
            continue
        evaled = d['pass'] + d['fail']
        pr = d['pass'] / evaled * 100 if evaled else 0
        print(f"  {risk:10s}: {d['pass']:4d}/{evaled:4d} ({pr:5.1f}%)")
    print()
    print("카테고리별 통과율 (상위):")
    cats = sorted(by_category.items(), key=lambda x: -x[1]['total'])[:15]
    for cat, d in cats:
        evaled = d['pass'] + d['fail']
        pr = d['pass'] / evaled * 100 if evaled else 0
        print(f"  {cat:24s}: {d['pass']:4d}/{evaled:4d} ({pr:5.1f}%) total={d['total']}")


if __name__ == '__main__':
    main()
