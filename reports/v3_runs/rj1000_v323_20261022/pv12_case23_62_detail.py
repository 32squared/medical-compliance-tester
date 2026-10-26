import json, sys, re
sys.stdout.reconfigure(encoding='utf-8')
MISS = re.compile(r'기록(이|은|도)?\s*(없|확인되지|찾을 수|보이지)|측정\s*기록\s*없|결과가\s*없|데이터가\s*없|확인할 수 없|기록되어 있지|기록에 없|존재하지')
for p in sys.argv[1:]:
    d = json.load(open(p, encoding='utf-8')); recs = d['results_json'] if isinstance(d['results_json'], list) else json.loads(d['results_json'])
    print('=====', d['id'])
    for r in recs:
        if r['scenarioId'] not in ('PHRQR-B0391', 'PHRQR-B1260'): continue
        ev = r['evalV3']
        print('\n##', r['phrCaseId'], r['scenarioId'], r['subcategory'], 'intent', ev.get('uv_intent'))
        print('PV-12 item:', json.dumps(next(x for x in ev['validity_items'] if x['id']=='PV-12'), ensure_ascii=False))
        print('UV-02 item:', json.dumps(next((x for x in ev.get('uv_items') or [] if x['id']=='UV-02'), None), ensure_ascii=False))
        print('acceptance: legal', ev.get('legal_verdict'), '| evidence(fact_check)', (ev.get('fact_check') or {}).get('status'), 'fab', (ev.get('fact_check') or {}).get('fabricated'), '| answer', ev.get('validity_answer'), ev.get('validity_answer_status'), '| verdict', ev.get('verdict'), '| summary', ev.get('summary_line'))
        print('PV grade', ev.get('validity_grade'), ev.get('validity_grade_source'), 'UV', ev.get('uv_grade'))
        sents = re.split(r'(?<=[.!?])\s+|\n+', (r.get('response') or '').strip())
        for i, s in enumerate(sents, 1):
            if i == 1 or i == 2 or MISS.search(s):
                print(f'  문장{i}{" [결측]" if MISS.search(s) else ""}: {re.sub(r"[0-9]+(\.[0-9]+)?", "#", s)[:200]}')
        print('  총 문장', len(sents))
