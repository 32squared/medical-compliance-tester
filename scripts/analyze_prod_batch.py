"""운영 batch 결과(test_runs.results_json) 분석 — v1.5.1 기준.

사용:
  python scripts/analyze_prod_batch.py /tmp/v151_1101_full.json
"""
import io
import json
import re
import sys
import statistics
from collections import Counter, defaultdict

if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

DEMOGRAPHIC_RE = re.compile(
    r'\d+\s*살|\d+\s*세|\d+\s*개월|\d+\s*년생|\d+\s*대(?:[\s남여])|미취학|소아|아이|어린이|아기|성인|중년|노인|할머니|할아버지|'
    r'여성|남성|여자|남자|아내|남편|엄마|아빠|어머니|아버지|'
    r'임신|임산부|임부|수유|모유|태아|산모|독거|치매|장애|면역저하|항암|투석'
)


def has_demographic(text):
    return bool(text and DEMOGRAPHIC_RE.search(text))


def has_demographic_missing(missing_list):
    if not isinstance(missing_list, list):
        return False
    return any(re.search(r'인구학|나이|연령|성별|임신|소아|고령', str(m)) for m in missing_list)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/v151_1101_full.json'
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    results = data.get('results') or []
    n = len(results)
    print('=' * 78)
    print(f'운영 batch v1.5.1 분석 — runId: {data.get("runId")}')
    print(f'env: {data.get("env")} · label: {data.get("label","")}')
    print(f'전체 시나리오: {n}건')
    print(f'summary: {data.get("summary")}')
    print('=' * 78)

    # consultationEval 있는 것만
    with_consult = [r for r in results if isinstance(r.get('consultationEval'), dict)
                    and r['consultationEval'].get('totalScore') is not None]
    print(f'\n[문진 평가 완료] {len(with_consult)}건  [미완료] {n-len(with_consult)}건')
    if not with_consult:
        print('완료된 평가가 없습니다')
        return

    # ── 1. 전체 점수 분포 ──
    scores = [r['consultationEval']['totalScore'] for r in with_consult]
    print('\n' + '─' * 50)
    print('1. 전체 문진 점수 분포 (v1.5.1)')
    print('─' * 50)
    print(f'  평균: {statistics.mean(scores):.1f}  중앙값: {statistics.median(scores):.0f}  표준편차: {statistics.stdev(scores) if len(scores)>1 else 0:.1f}')
    print(f'  최소: {min(scores)}  최대: {max(scores)}')
    grades = Counter(r['consultationEval'].get('grade','?') for r in with_consult)
    print(f'  등급 분포:')
    for g in ['A', 'B', 'C', 'D', 'F']:
        cnt = grades.get(g, 0)
        pct = cnt / len(with_consult) * 100
        bar = '█' * int(pct / 2)
        print(f'    {g} ({cnt:4d}건, {pct:5.1f}%) {bar}')

    # ── 2. 축별 평균 (v1.5.1) ──
    print('\n' + '─' * 50)
    print('2. 축별 평균 점수 (v1.5.1)')
    print('─' * 50)
    AXIS_INFO = [
        ('safetyDisclosure',   '의료법 경계·안전 고지', 15),
        ('redFlagAwareness',   '위험 신호 인식·전달',   25),
        ('consultationFlow',   '문진 Flow 명시',         25),
        ('clinicalValue',      '환자 맞춤·임상가치',     22),
        ('actionAndCommunication', '행동 가이드·의사소통', 13),
    ]
    for key, name, mx in AXIS_INFO:
        vals = [r['consultationEval'].get('axes', {}).get(key, {}).get('score', 0) for r in with_consult]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            a = statistics.mean(vals)
            print(f'  {name:25s} {a:5.2f} / {mx} ({a/mx*100:5.1f}%)')

    # ── 3. 인구학 활용 통계 ──
    print('\n' + '═' * 50)
    print('3. 🎯 인구학 정보 활용 통계 (v1.5.1 핵심)')
    print('═' * 50)
    has_demo_count = 0
    cv_with_demo, cv_no_demo = [], []
    demo_missed_count = 0
    for r in with_consult:
        prompt = r.get('prompt', '')
        cv = r['consultationEval'].get('axes', {}).get('clinicalValue', {})
        cv_score = cv.get('score', 0)
        if has_demographic(prompt):
            has_demo_count += 1
            cv_with_demo.append(cv_score)
            if has_demographic_missing(cv.get('missing', [])):
                demo_missed_count += 1
        else:
            cv_no_demo.append(cv_score)
    print(f'\n[인구학 정보가 prompt에 명시된 시나리오]')
    print(f'  명시: {has_demo_count}건 ({has_demo_count/len(with_consult)*100:.1f}%)')
    print(f'  미명시: {len(with_consult)-has_demo_count}건')
    print(f'\n[clinicalValue 축 점수 분포 (22점 만점)]')
    all_cv = cv_with_demo + cv_no_demo
    print(f'  전체 평균: {statistics.mean(all_cv):.2f} / 22 ({statistics.mean(all_cv)/22*100:.1f}%)')
    if cv_with_demo:
        print(f'  인구학 명시 prompt: 평균 {statistics.mean(cv_with_demo):.2f} / 22')
    if cv_no_demo:
        print(f'  인구학 미명시 prompt: 평균 {statistics.mean(cv_no_demo):.2f} / 22')
    if has_demo_count > 0:
        print(f'\n[인구학 미활용 명시 기록]')
        print(f'  인구학 명시 시나리오 중 missing에 "인구학 미활용" 기록: {demo_missed_count}/{has_demo_count}건 ({demo_missed_count/has_demo_count*100:.1f}%)')

    # ── 4. 법률 평가 분포 ──
    legal_scores = [r['gptEval']['score'] for r in with_consult
                    if isinstance(r.get('gptEval'), dict) and r['gptEval'].get('score') is not None]
    if legal_scores:
        print('\n' + '─' * 50)
        print(f'4. GPT 법률 평가 ({len(legal_scores)}건)')
        print('─' * 50)
        print(f'  평균: {statistics.mean(legal_scores):.1f}  중앙값: {statistics.median(legal_scores):.0f}')
        legal_grades = Counter(r['gptEval'].get('grade', '?') for r in with_consult if isinstance(r.get('gptEval'), dict))
        for g in ['A', 'B', 'C', 'D', 'F']:
            cnt = legal_grades.get(g, 0)
            if cnt > 0:
                print(f'    {g}: {cnt}건 ({cnt/len(legal_scores)*100:.1f}%)')

    # ── 5. 카테고리별 ──
    cat_scores = defaultdict(list)
    for r in with_consult:
        cat = r.get('category') or '미분류'
        cat_scores[cat].append(r['consultationEval']['totalScore'])
    if len(cat_scores) > 1:
        print('\n' + '─' * 50)
        print('5. 카테고리별 평균 (Top 15)')
        print('─' * 50)
        cat_avgs = [(c, statistics.mean(s), len(s)) for c, s in cat_scores.items() if len(s) >= 2]
        for cat, av, cnt in sorted(cat_avgs, key=lambda x: -x[1])[:15]:
            print(f'  {cat:30s} 평균 {av:5.1f}  ({cnt:3d}건)')

    # ── 6. 위험도별 ──
    risk_scores = defaultdict(list)
    for r in with_consult:
        rl = r.get('riskLevel') or '미분류'
        risk_scores[rl].append(r['consultationEval']['totalScore'])
    if len(risk_scores) > 1:
        print('\n' + '─' * 50)
        print('6. 위험도별 평균')
        print('─' * 50)
        for risk, scs in sorted(risk_scores.items()):
            print(f'  {risk:15s} 평균 {statistics.mean(scs):5.1f}  ({len(scs):3d}건)')

    # ── 7. 자주 누락된 핵심 ──
    all_missing = []
    for r in with_consult:
        ms = r['consultationEval'].get('missingItems', [])
        if isinstance(ms, list):
            all_missing.extend(ms)
    if all_missing:
        print('\n' + '─' * 50)
        print('7. 자주 누락된 핵심 항목 (Top 20)')
        print('─' * 50)
        miss_counts = Counter(str(m)[:70] for m in all_missing)
        for item, cnt in miss_counts.most_common(20):
            print(f'  {cnt:4d}건: {item}')

    print('\n' + '=' * 78)
    print('분석 완료')
    print('=' * 78)


if __name__ == '__main__':
    main()
