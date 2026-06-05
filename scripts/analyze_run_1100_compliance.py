"""1100건 배치의 컴플라이언스 위반 심층 분석.

각 위반 항목의 law / type / severity / description 4개 필드를 풀어
법 조항별 / 심각도별 / 카테고리별 / 시나리오별 매트릭스 산출.

사용:
  python scripts/analyze_run_1100_compliance.py data/run-1e71ae.json data/run-1e71ae-compliance.json
"""
import json
import os
import re
import statistics
import sys
from collections import Counter, defaultdict


def normalize_law(law_str):
    """law 문자열을 4개 표준 그룹으로 정규화."""
    if not law_str:
        return '미분류'
    s = law_str.strip()
    # 응급의료법 우선 (조합도 일단 응급의료법으로)
    has_emergency = '응급의료' in s
    has_27 = '제27조' in s or '27조' in s
    has_56 = '제56조' in s or '56조' in s
    if has_27 and has_emergency:
        return '의료법 27조 + 응급의료법'
    if has_emergency:
        return '응급의료에 관한 법률'
    if has_27 and has_56:
        return '의료법 27조 + 56조'
    if has_56:
        return '의료법 제56조 (과대광고)'
    if has_27:
        return '의료법 제27조 (무면허 의료행위)'
    if '내부' in s or '평가 기준' in s or '가이드' in s or '면책' in s or '필수' in s:
        return '내부 평가/준수 기준'
    return '미분류'


def normalize_type(type_str):
    """위반 유형 문자열을 카테고리 그룹으로 정규화."""
    if not type_str:
        return '기타'
    s = type_str.strip()
    if '필수' in s and ('고정' in s or '문구' in s):
        if '말미' in s:
            return '필수 말미 문구 누락'
        return '필수 고정 문구 누락'
    if '검사' in s or '시술' in s or '치료' in s and '관련 지시' in s:
        if '지시' in s:
            return '검사·시술·치료 지시'
    if '검사' in s and '지시' in s:
        return '검사·시술·치료 지시'
    if '치료' in s and '지시' in s:
        return '검사·시술·치료 지시'
    if '시술' in s and '지시' in s:
        return '검사·시술·치료 지시'
    if '처방' in s or '복약' in s or '용량' in s:
        return '처방·복약 지시'
    if '응급' in s and ('내원' in s or '필요성' in s or '분류' in s):
        return '응급/내원 단정·분류'
    if '응급 안내' in s:
        return '응급 안내 미흡'
    if '병명' in s and '단정' in s:
        return '병명 단정 표현'
    if '개인 맞춤' in s and ('치료' in s or '관리' in s):
        return '개인 맞춤 치료/관리 지시'
    if '진료' in s and '필요성' in s:
        return '진료 필요성 단정'
    return s[:30]


def main():
    inp = sys.argv[1] if len(sys.argv) > 1 else 'data/run-1e71ae.json'
    outp = sys.argv[2] if len(sys.argv) > 2 else 'data/run-1e71ae-compliance.json'

    with open(inp, 'r', encoding='utf-8') as f:
        d = json.load(f)
    results = d['results_json']
    total = len(results)

    out = {
        'meta': {
            'id': d.get('id'),
            'run_at': d.get('run_at'),
            'env': d.get('env'),
            'total': total,
        }
    }

    # ───────────────────────────────────────
    # 1. 위반 발생률
    # ───────────────────────────────────────
    has_viol = sum(1 for r in results if (r.get('gptEval') or {}).get('violations'))
    out['overview'] = {
        'total_scenarios': total,
        'clean_scenarios': total - has_viol,
        'violated_scenarios': has_viol,
        'clean_rate': (total - has_viol) / total * 100,
        'violated_rate': has_viol / total * 100,
    }

    # 시나리오당 위반 개수 분포
    viol_per_scenario = Counter()
    for r in results:
        viols = (r.get('gptEval') or {}).get('violations') or []
        viol_per_scenario[len(viols)] += 1
    out['viol_distribution'] = dict(sorted(viol_per_scenario.items()))

    # 총 위반 항목 수
    total_viol_items = sum(len((r.get('gptEval') or {}).get('violations') or []) for r in results)
    out['total_violation_items'] = total_viol_items

    # ───────────────────────────────────────
    # 2. 법 조항별 / severity 별
    # ───────────────────────────────────────
    law_counter = Counter()
    sev_counter = Counter()
    law_sev = defaultdict(Counter)  # law → severity → count
    type_counter = Counter()
    type_law = defaultdict(Counter)  # type → law → count
    type_sev = defaultdict(Counter)  # type → severity → count

    for r in results:
        viols = (r.get('gptEval') or {}).get('violations') or []
        for v in viols:
            if not isinstance(v, dict):
                continue
            law = normalize_law(v.get('law', ''))
            sev = (v.get('severity') or '').upper().strip() or 'UNKNOWN'
            typ = normalize_type(v.get('type', ''))
            law_counter[law] += 1
            sev_counter[sev] += 1
            law_sev[law][sev] += 1
            type_counter[typ] += 1
            type_law[typ][law] += 1
            type_sev[typ][sev] += 1

    out['by_law'] = dict(law_counter.most_common())
    out['by_severity'] = dict(sev_counter.most_common())
    out['law_severity_matrix'] = {l: dict(s) for l, s in law_sev.items()}
    out['by_type'] = dict(type_counter.most_common(20))
    out['type_law_matrix'] = {t: dict(law_counter) for t, law_counter in type_law.items()
                              if t in dict(type_counter.most_common(20))}
    out['type_severity_matrix'] = {t: dict(sev) for t, sev in type_sev.items()
                                    if t in dict(type_counter.most_common(20))}

    # ───────────────────────────────────────
    # 3. 카테고리 × 위반유형
    # ───────────────────────────────────────
    cat_type = defaultdict(Counter)
    cat_total = Counter()
    for r in results:
        cat = r.get('category') or 'unknown'
        cat_total[cat] += 1
        for v in ((r.get('gptEval') or {}).get('violations') or []):
            if not isinstance(v, dict):
                continue
            cat_type[cat][normalize_type(v.get('type', ''))] += 1
    # 카테고리 모수 ≥ 50 만 (의미있는 표본)
    out['category_type_matrix'] = {
        c: {'total': cat_total[c], 'violations': dict(cat_type[c].most_common(10))}
        for c in sorted(cat_total.keys()) if cat_total[c] >= 50
    }

    # ───────────────────────────────────────
    # 4. CRITICAL 위반 사례 (description 직접)
    # ───────────────────────────────────────
    critical_cases = []
    for r in results:
        viols = (r.get('gptEval') or {}).get('violations') or []
        crit_viols = [v for v in viols if isinstance(v, dict) and v.get('severity', '').upper() == 'CRITICAL']
        if crit_viols:
            critical_cases.append({
                'scenarioId': r.get('scenarioId'),
                'category': r.get('category'),
                'subcategory': r.get('subcategory'),
                'finalScore': r.get('finalScore'),
                'grade': (r.get('gptEval') or {}).get('grade'),
                'riskLevel': r.get('riskLevel'),
                'critical_count': len(crit_viols),
                'critical_violations': [
                    {
                        'law': v.get('law', ''),
                        'type': v.get('type', ''),
                        'description': v.get('description', '')[:300],
                    } for v in crit_viols[:3]
                ]
            })
    # 점수 낮은 순으로 정렬
    critical_cases.sort(key=lambda x: x['finalScore'] or 0)
    out['critical_cases'] = critical_cases[:15]
    out['critical_case_count'] = len(critical_cases)

    # ───────────────────────────────────────
    # 5. 다중 위반 시나리오 (3개 이상)
    # ───────────────────────────────────────
    multi_viol = []
    for r in results:
        viols = (r.get('gptEval') or {}).get('violations') or []
        if len(viols) >= 4:
            multi_viol.append({
                'scenarioId': r.get('scenarioId'),
                'category': r.get('category'),
                'subcategory': (r.get('subcategory') or '')[:30],
                'finalScore': r.get('finalScore'),
                'grade': (r.get('gptEval') or {}).get('grade'),
                'riskLevel': r.get('riskLevel'),
                'violation_count': len(viols),
                'severity_breakdown': dict(Counter(v.get('severity', 'UNKNOWN').upper() for v in viols if isinstance(v, dict))),
                'top_types': [normalize_type(v.get('type', '')) for v in viols if isinstance(v, dict)][:5],
            })
    multi_viol.sort(key=lambda x: (-x['violation_count'], x['finalScore'] or 0))
    out['multi_violation_scenarios'] = multi_viol[:15]
    out['multi_violation_count'] = len(multi_viol)

    # ───────────────────────────────────────
    # 6. risk_level × severity 매트릭스 (응급 시나리오에서 위반이 더 위험)
    # ───────────────────────────────────────
    risk_sev = defaultdict(Counter)
    risk_total_viols = Counter()
    risk_scenarios = Counter()
    for r in results:
        risk = r.get('riskLevel') or 'UNKNOWN'
        risk_scenarios[risk] += 1
        for v in ((r.get('gptEval') or {}).get('violations') or []):
            if isinstance(v, dict):
                sev = v.get('severity', 'UNKNOWN').upper()
                risk_sev[risk][sev] += 1
                risk_total_viols[risk] += 1
    out['risk_severity_matrix'] = {
        risk: {
            'scenarios': risk_scenarios[risk],
            'total_violations': risk_total_viols[risk],
            'avg_viol_per_scenario': risk_total_viols[risk] / risk_scenarios[risk] if risk_scenarios[risk] else 0,
            'by_severity': dict(risk_sev[risk]),
        }
        for risk in ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW'] if risk in risk_scenarios
    }

    # ───────────────────────────────────────
    # 7. 컴플라이언스 위험 우선순위 표
    # severity (CRITICAL=3, HIGH=2, MEDIUM=1, LOW=0.5) × 빈도 = 가중치
    # ───────────────────────────────────────
    sev_weight = {'CRITICAL': 3, 'HIGH': 2, 'MEDIUM': 1, 'LOW': 0.5}
    type_weighted = []
    for typ, n in type_counter.most_common(20):
        ts = type_sev.get(typ, Counter())
        weight = sum(ts.get(s, 0) * w for s, w in sev_weight.items())
        type_weighted.append({
            'type': typ,
            'count': n,
            'weighted_score': weight,
            'severity': dict(ts),
            'primary_law': max(type_law[typ].items(), key=lambda kv: kv[1])[0] if type_law[typ] else '',
        })
    type_weighted.sort(key=lambda x: -x['weighted_score'])
    out['priority_violations'] = type_weighted[:12]

    # ───────────────────────────────────────
    # 8. clean 시나리오 (위반 0건) 카테고리별
    # ───────────────────────────────────────
    cat_clean = Counter()
    for r in results:
        if not ((r.get('gptEval') or {}).get('violations')):
            cat_clean[r.get('category') or 'unknown'] += 1
    out['clean_by_category'] = {
        c: {
            'clean': cat_clean[c],
            'total': cat_total[c],
            'clean_rate': cat_clean[c] / cat_total[c] * 100 if cat_total[c] else 0,
        }
        for c in cat_total.keys() if cat_total[c] >= 50
    }

    # ───────────────────────────────────────
    # 9. severity별 평균 점수 영향
    # ───────────────────────────────────────
    sev_scores = defaultdict(list)
    for r in results:
        score = r.get('finalScore') or 0
        viols = (r.get('gptEval') or {}).get('violations') or []
        max_sev = None
        for v in viols:
            if isinstance(v, dict):
                s = v.get('severity', '').upper()
                if s == 'CRITICAL':
                    max_sev = 'CRITICAL'
                    break
                elif s == 'HIGH' and max_sev != 'CRITICAL':
                    max_sev = 'HIGH'
                elif s == 'MEDIUM' and max_sev not in ('CRITICAL', 'HIGH'):
                    max_sev = 'MEDIUM'
                elif s == 'LOW' and max_sev is None:
                    max_sev = 'LOW'
        if max_sev is None:
            max_sev = 'NONE'
        sev_scores[max_sev].append(score)
    out['score_by_max_severity'] = {
        s: {
            'count': len(v),
            'mean': statistics.mean(v) if v else 0,
            'median': statistics.median(v) if v else 0,
        }
        for s, v in sev_scores.items()
    }

    # 결과 저장 + 콘솔 요약 출력
    os.makedirs(os.path.dirname(outp), exist_ok=True)
    with open(outp, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'분석 저장: {outp}')

    print()
    print(f'=== 컴플라이언스 위반 분석 요약 ===')
    print(f'총 시나리오: {out["overview"]["total_scenarios"]}')
    print(f'  - 위반 없음(clean): {out["overview"]["clean_scenarios"]} ({out["overview"]["clean_rate"]:.1f}%)')
    print(f'  - 위반 보유: {out["overview"]["violated_scenarios"]} ({out["overview"]["violated_rate"]:.1f}%)')
    print(f'총 위반 항목: {out["total_violation_items"]}')
    print()
    print(f'[법 조항별]')
    for law, n in list(out['by_law'].items())[:6]:
        print(f'  {law:35s} {n:5d}회')
    print()
    print(f'[심각도별]')
    for sev, n in out['by_severity'].items():
        pct = n / out['total_violation_items'] * 100
        print(f'  {sev:10s} {n:5d}회 ({pct:.1f}%)')
    print()
    print(f'CRITICAL 위반 보유 시나리오: {out["critical_case_count"]}건')
    print(f'다중 위반(4개 이상) 시나리오: {out["multi_violation_count"]}건')
    print()
    print(f'[우선순위 가중 위반 유형 Top 5]')
    for v in out['priority_violations'][:5]:
        print(f'  {v["type"][:25]:25s} count={v["count"]:4d}  weight={v["weighted_score"]:6.0f}  주조항={v["primary_law"]}')


if __name__ == '__main__':
    main()
