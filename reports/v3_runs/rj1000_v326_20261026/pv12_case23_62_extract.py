import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
def load(p):
    d = json.load(open(p, encoding='utf-8'))
    recs = d['results_json'] if isinstance(d.get('results_json'), list) else json.loads(d['results_json'])
    return d, recs
d22, r22 = load(sys.argv[1]); d20, r20 = load(sys.argv[2])
print('run22', d22['id'], d22['run_at'], 'n', len(r22)); print('run20', d20['id'], d20['run_at'], 'n', len(r20))
by20 = {r['scenarioId']: r for r in r20}
MISS = re.compile(r'기록(이|은|도)?\s*(없|확인되지|찾을 수|보이지)|측정\s*기록\s*없|결과가\s*없|데이터가\s*없|확인할 수 없|기록되어 있지|기록에 없|존재하지')
def first_sent(txt):
    s = re.split(r'(?<=[.!?。])\s+|\n+', (txt or '').strip())
    return s[0] if s else ''
targets = {'phr_CASE-23', 'phr_CASE-62'}
rows = []
for r in r22:
    if r.get('phrCaseId') not in targets: continue
    ev = r.get('evalV3') or {}
    it = next((x for x in ev.get('validity_items') or [] if x.get('id') == 'PV-12'), None)
    o = by20.get(r['scenarioId']) or {}; oev = o.get('evalV3') or {}
    oit = next((x for x in oev.get('validity_items') or [] if x.get('id') == 'PV-12'), None)
    resp = r.get('response') or ''
    miss_sents = [i+1 for i, s in enumerate(re.split(r'(?<=[.!?])\s+|\n+', resp.strip())) if MISS.search(s)]
    rows.append(dict(case=r['phrCaseId'], sid=r['scenarioId'], T=r.get('subcategory'), prompt=r.get('prompt'),
        pv12_22=(it or {}).get('result'), det22=(it or {}).get('detail'),
        pv12_20=(oit or {}).get('result'), det20=(oit or {}).get('detail'),
        grade22=ev.get('validity_grade'), unmet22=ev.get('validity_unmet'), uv22=ev.get('uv_grade'), uvunmet=ev.get('uv_unmet'), intent=ev.get('uv_intent'),
        vsrc=ev.get('validity_grade_source'), miss_sents=miss_sents, first=first_sent(resp)[:160], nsent=len(re.split(r'(?<=[.!?])\s+|\n+', resp.strip()))))
rows.sort(key=lambda x: (x['case'], x['sid']))
for x in rows:
    print(f"\n{x['case']} {x['sid']} {x['T']} intent={x['intent']} | PV-12 10/22={x['pv12_22']} det={x['det22']!r} | 10/20={x['pv12_20']} det={x['det20']!r} | PV등급={x['grade22']}({x['vsrc']}) unmet={x['unmet22']} UV={x['uv22']} unmet={x['uvunmet']}")
    print(f"   Q: {x['prompt']}")
    print(f"   결측문장번호={x['miss_sents']} (총 {x['nsent']}문장) 첫문장: {x['first']}")
# PV-12 전체 분포 + 모든 unmet
print('\n=== 10/22 PV-12 전체 분포'); from collections import Counter
c = Counter(); unmet=[]
for r in r22:
    it = next((x for x in (r.get('evalV3') or {}).get('validity_items') or [] if x.get('id')=='PV-12'), None)
    c[(it or {}).get('result')] += 1
    if it and it.get('result')=='unmet': unmet.append((r['phrCaseId'], r['scenarioId'], r.get('subcategory'), it.get('detail')))
print(c); print('unmet:', unmet)
print('=== 10/20 PV-12 unmet')
for r in r20:
    it = next((x for x in (r.get('evalV3') or {}).get('validity_items') or [] if x.get('id')=='PV-12'), None)
    if it and it.get('result')=='unmet': print(r['phrCaseId'], r['scenarioId'], r.get('subcategory'), it.get('detail'))
