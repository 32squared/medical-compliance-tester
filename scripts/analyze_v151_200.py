"""v1.5.1 200건 평가 결과 분석 — 인구학 활용 통계 포함.

사용:
  python scripts/analyze_v151_200.py /tmp/v151_200.json
"""
import io
import json
import re
import sys
import statistics
from collections import Counter, defaultdict

# Windows cp949 회피 — UTF-8 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# 인구학 정보 감지 정규식 (prompt에 명시되었는지 확인)
DEMOGRAPHIC_PATTERNS = [
    (r'(\d+)\s*살|(\d+)\s*세|(\d+)\s*개월|(\d+)\s*주|(\d+)\s*년생|미취학|소아|아이|어린이|아기|어른|성인|중년|노인|할머니|할아버지', 'age'),
    (r'(\d+)\s*대(?:\s|$|남자|여자|남성|여성)|20대|30대|40대|50대|60대|70대|80대', 'age_range'),
    (r'여성|남성|여자|남자|아내|남편|엄마|아빠|어머니|아버지|어머님|아버님', 'gender'),
    (r'임신|임산부|임부|수유|모유|태아|산모', 'pregnancy'),
    (r'독거|치매|장애|면역저하|항암|투석', 'special'),
]


def detect_demographics(text):
    """prompt에서 인구학 정보 감지. 매칭된 카테고리 set 반환."""
    if not text:
        return set()
    found = set()
    for pattern, cat in DEMOGRAPHIC_PATTERNS:
        if re.search(pattern, text):
            found.add(cat)
    return found


def has_demographic_missing(missing_list):
    """clinicalValue.missing 에 인구학 미활용 표시 있는지."""
    if not isinstance(missing_list, list):
        return False
    text = ' '.join(str(m) for m in missing_list)
    return bool(re.search(r'인구학|나이|연령|성별|임신|소아|고령', text))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else '/tmp/v151_200.json'
    with open(path, encoding='utf-8') as f:
        data = json.load(f)

    results = data.get('results') or []
    n = len(results)
    print('=' * 78)
    print(f'v1.5.1 200건 평가 분석 (실제 {n}건)')
    print(f"GPT 모델: {data.get('gptModel')}, run_id: {data.get('runId')}")
    print('=' * 78)

    # 실패 분리
    succeeded = [r for r in results if r.get('v151', {}).get('totalScore') is not None]
    failed = [r for r in results if r.get('v151', {}).get('totalScore') is None]
    print(f'\n[성공] {len(succeeded)}건  [실패] {len(failed)}건')

    if failed:
        print(f'\n실패 사유 상위 3:')
        errs = Counter([str(r.get('v151', {}).get('error',''))[:60] for r in failed])
        for err, cnt in errs.most_common(3):
            print(f'  {cnt}건: {err}')

    if not succeeded:
        sys.exit('성공한 평가가 없음')

    # ─────────────────────────────────────
    # 1. 전체 점수 분포
    # ─────────────────────────────────────
    scores = [r['v151']['totalScore'] for r in succeeded]
    avg = statistics.mean(scores)
    med = statistics.median(scores)
    std = statistics.stdev(scores) if len(scores) > 1 else 0
    print('\n' + '─' * 50)
    print('1. 전체 점수 분포 (v1.5.1)')
    print('─' * 50)
    print(f'  평균: {avg:.1f}  중앙값: {med:.0f}  표준편차: {std:.1f}')
    print(f'  최소: {min(scores)}  최대: {max(scores)}')
    grades = Counter(r['v151']['grade'] for r in succeeded)
    print(f'  등급 분포:')
    for g in ['A', 'B', 'C', 'D', 'F']:
        cnt = grades.get(g, 0)
        pct = cnt / len(succeeded) * 100
        bar = '█' * int(pct / 2)
        print(f'    {g} ({cnt:3d}건, {pct:5.1f}%) {bar}')

    # ─────────────────────────────────────
    # 2. 축별 평균 점수
    # ─────────────────────────────────────
    print('\n' + '─' * 50)
    print('2. 축별 평균 점수')
    print('─' * 50)
    AXIS_INFO = [
        ('safetyDisclosure',   '의료법 경계·안전 고지', 15),
        ('redFlagAwareness',   '위험 신호 인식·전달',   25),
        ('consultationFlow',   '문진 Flow 명시',         25),
        ('clinicalValue',      '환자 맞춤·임상가치',     22),
        ('actionAndCommunication', '행동 가이드·의사소통', 13),
    ]
    for key, name, mx in AXIS_INFO:
        vals = [r['v151'].get('axes', {}).get(key, {}).get('score', 0) for r in succeeded]
        vals = [v for v in vals if isinstance(v, (int, float))]
        if vals:
            a = statistics.mean(vals)
            pct = a / mx * 100
            print(f'  {name:25s} {a:5.2f} / {mx} ({pct:5.1f}%)')

    # ─────────────────────────────────────
    # 3. 🎯 인구학 정보 활용 통계 (v1.5.1 핵심)
    # ─────────────────────────────────────
    print('\n' + '═' * 50)
    print('3. 🎯 인구학 정보 활용 통계 (v1.5.1 핵심)')
    print('═' * 50)

    # prompt에서 인구학 정보 자동 감지
    demographics_in_prompt = [detect_demographics(r.get('prompt', '')) for r in succeeded]
    has_demo = [bool(d) for d in demographics_in_prompt]
    n_has_demo = sum(has_demo)
    print(f'\n[인구학 정보가 prompt에 명시된 시나리오]')
    print(f'  명시: {n_has_demo}건 ({n_has_demo/len(succeeded)*100:.1f}%)')
    print(f'  미명시: {len(succeeded) - n_has_demo}건')

    if n_has_demo > 0:
        # 카테고리별
        cat_counts = Counter()
        for d in demographics_in_prompt:
            for c in d:
                cat_counts[c] += 1
        print(f'\n  인구학 카테고리 분포 (중복 카운트):')
        labels = {'age':'나이', 'age_range':'연령대', 'gender':'성별',
                  'pregnancy':'임신/수유', 'special':'특수 상황'}
        for c, cnt in cat_counts.most_common():
            print(f'    {labels.get(c, c):8s} {cnt}건')

    # 인구학 항목 점수 분포 (7점 만점)
    demo_scores = []
    for r, has_d in zip(succeeded, has_demo):
        axes = r['v151'].get('axes', {})
        cv = axes.get('clinicalValue', {})
        # clinicalValue 자체에 인구학 항목별 세부 점수 없음 (총합으로 옴)
        # 대신 missing 텍스트로 추정
        cv_score = cv.get('score', 0)
        cv_missing = cv.get('missing', [])
        demo_missed = has_demographic_missing(cv_missing)
        demo_scores.append((has_d, cv_score, demo_missed, cv_missing))

    print(f'\n[clinicalValue 축 점수 분포 (22점 만점)]')
    cv_vals = [s for _, s, _, _ in demo_scores]
    cv_avg = statistics.mean(cv_vals)
    print(f'  평균: {cv_avg:.2f} / 22 ({cv_avg/22*100:.1f}%)')
    cv_with_demo = [s for hd, s, _, _ in demo_scores if hd]
    cv_no_demo = [s for hd, s, _, _ in demo_scores if not hd]
    if cv_with_demo:
        print(f'  인구학 명시 prompt: 평균 {statistics.mean(cv_with_demo):.2f} / 22')
    if cv_no_demo:
        print(f'  인구학 미명시 prompt: 평균 {statistics.mean(cv_no_demo):.2f} / 22')

    # 인구학 미활용 명시 기록 건수
    n_demo_missed = sum(1 for hd, _, missed, _ in demo_scores if hd and missed)
    if n_has_demo > 0:
        print(f'\n[인구학 미활용 명시 기록]')
        print(f'  인구학 명시 시나리오 중 missing에 "인구학 미활용" 기록: {n_demo_missed}/{n_has_demo}건 ({n_demo_missed/n_has_demo*100:.1f}%)')
        print(f'  → GPT가 인구학 정보를 답변에 반영 안 한 사례 비율')

    # ─────────────────────────────────────
    # 4. v1.0 비교 (있는 경우)
    # ─────────────────────────────────────
    has_v0 = [r for r in succeeded if r.get('v0_consultationEval', {}).get('totalScore') is not None]
    if has_v0:
        print('\n' + '─' * 50)
        print(f'4. v1.0 → v1.5.1 비교 ({len(has_v0)}건)')
        print('─' * 50)
        v0_scores = [r['v0_consultationEval']['totalScore'] for r in has_v0]
        v151_scores = [r['v151']['totalScore'] for r in has_v0]
        diffs = [b - a for a, b in zip(v0_scores, v151_scores)]
        print(f'  v1.0  평균: {statistics.mean(v0_scores):.1f}')
        print(f'  v1.5.1 평균: {statistics.mean(v151_scores):.1f}')
        print(f'  점수 변화: 평균 {statistics.mean(diffs):+.1f}  (양수=v1.5.1이 더 높음)')
        higher = sum(1 for d in diffs if d > 0)
        lower = sum(1 for d in diffs if d < 0)
        same = sum(1 for d in diffs if d == 0)
        print(f'  v1.5.1이 더 높음: {higher}건 / 더 낮음: {lower}건 / 동일: {same}건')

    # ─────────────────────────────────────
    # 5. 카테고리별 평균
    # ─────────────────────────────────────
    cat_scores = defaultdict(list)
    for r in succeeded:
        cat = r.get('category') or '미분류'
        cat_scores[cat].append(r['v151']['totalScore'])
    if len(cat_scores) > 1:
        print('\n' + '─' * 50)
        print('5. 카테고리별 평균 점수 (Top 10)')
        print('─' * 50)
        cat_avgs = [(cat, statistics.mean(scs), len(scs))
                    for cat, scs in cat_scores.items() if len(scs) >= 2]
        for cat, av, cnt in sorted(cat_avgs, key=lambda x: -x[1])[:10]:
            print(f'  {cat:25s} 평균 {av:5.1f}  ({cnt}건)')

    # ─────────────────────────────────────
    # 6. 위험도별 평균
    # ─────────────────────────────────────
    risk_scores = defaultdict(list)
    for r in succeeded:
        rl = r.get('riskLevel') or '미분류'
        risk_scores[rl].append(r['v151']['totalScore'])
    if len(risk_scores) > 1:
        print('\n' + '─' * 50)
        print('6. 위험도별 평균 점수')
        print('─' * 50)
        for risk, scs in sorted(risk_scores.items()):
            if len(scs) >= 1:
                print(f'  {risk:15s} 평균 {statistics.mean(scs):5.1f}  ({len(scs)}건)')

    # ─────────────────────────────────────
    # 7. 자주 누락된 항목 (전체 missingItems)
    # ─────────────────────────────────────
    all_missing = []
    for r in succeeded:
        ms = r['v151'].get('missingItems', [])
        if isinstance(ms, list):
            all_missing.extend(ms)
    if all_missing:
        print('\n' + '─' * 50)
        print('7. 자주 누락된 핵심 항목 (Top 15)')
        print('─' * 50)
        miss_counts = Counter(str(m)[:60] for m in all_missing)
        for item, cnt in miss_counts.most_common(15):
            print(f'  {cnt:3d}건: {item}')

    print('\n' + '=' * 78)
    print('분석 완료')
    print('=' * 78)


if __name__ == '__main__':
    main()
