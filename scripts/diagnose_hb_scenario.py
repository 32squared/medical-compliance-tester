"""특정 HB 시나리오의 PROD DB 상태 진단.

scenarios 테이블 + test_runs 모두 검사:
- 시나리오 자체 존재 여부 + 메타 (turns/rubric/tags)
- 어느 run 의 results 에 해당 scenarioId 가 들어있는지
- 그 result entry 의 핵심 필드 (rubricEval.score / turnResults / response)

실행: VERIFY_SCENARIO_ID=HB-C0D1DD5E python scripts/diagnose_hb_scenario.py
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db


def main():
    sid = os.environ.get('VERIFY_SCENARIO_ID', '').strip()
    if not sid:
        raise SystemExit('VERIFY_SCENARIO_ID env var 필요')

    print(f'=== HB 시나리오 진단: {sid} ===', flush=True)
    print('', flush=True)

    # 1. scenarios 테이블 직접 조회
    s = db.get_scenario(sid)
    if s:
        print(f'[scenarios 테이블] ✓ 존재', flush=True)
        print(f'  category: {s.get("category")}', flush=True)
        print(f'  subcategory: {s.get("subcategory")}', flush=True)
        print(f'  riskLevel: {s.get("riskLevel")}', flush=True)
        print(f'  source: {s.get("source")}', flush=True)
        print(f'  tags: {s.get("tags")}', flush=True)
        print(f'  turns count: {len(s.get("turns") or [])}', flush=True)
        print(f'  rubric count: {len(s.get("rubric") or [])}', flush=True)
        print(f'  prompt[:80]: {(s.get("prompt") or "")[:80]}', flush=True)
        gen = s.get('generationInfo') or {}
        print(f'  generationInfo.prompt_id: {gen.get("prompt_id")}', flush=True)
    else:
        print(f'[scenarios 테이블] ✗ 시나리오 없음 (DB에서 못 찾음)', flush=True)
    print('', flush=True)

    # 2. test_runs 검사 — 어느 run 의 results 에 이 scenarioId 있는지
    test_runs = db.get_test_runs(limit=500)
    print(f'[test_runs 검사] 총 {len(test_runs)}개 run 검색 중...', flush=True)
    matched_runs = []
    for r in test_runs:
        run_id = r.get('id')
        results_raw = r.get('results') or r.get('results_json')
        if isinstance(results_raw, str):
            try:
                results = json.loads(results_raw)
            except Exception:
                results = []
        elif isinstance(results_raw, list):
            results = results_raw
        else:
            results = []
        for res in results:
            if res.get('scenarioId') == sid:
                matched_runs.append({
                    'run_id': run_id,
                    'started_at': r.get('runAt'),
                    'status': r.get('status'),
                    'result': res,
                })
                break

    print(f'  매칭된 run: {len(matched_runs)}개', flush=True)
    print('', flush=True)

    for i, m in enumerate(matched_runs[:5]):
        print(f'--- run {i+1}: {m["run_id"]} ---', flush=True)
        print(f'  startedAt: {m["started_at"]}', flush=True)
        print(f'  run status: {m["status"]}', flush=True)
        res = m['result']
        print(f'  result.status: {res.get("status")}', flush=True)
        print(f'  result.finalScore: {res.get("finalScore")}', flush=True)
        print(f'  result.finalSource: {res.get("finalSource")}', flush=True)
        print(f'  result.responseLength: {res.get("responseLength")}', flush=True)
        print(f'  result.responseTime: {res.get("responseTime")} ms', flush=True)
        print(f'  result.turnsExecuted: {res.get("turnsExecuted")}', flush=True)
        print(f'  result.turnsTotal: {res.get("turnsTotal")}', flush=True)
        tr = res.get('turnResults') or []
        print(f'  result.turnResults: {len(tr)}개', flush=True)
        if tr:
            print(f'    turn[0]: query len={len(tr[0].get("query","") or "")} response len={len(tr[0].get("response","") or "")}', flush=True)
            print(f'    turn[-1]: query len={len(tr[-1].get("query","") or "")} response len={len(tr[-1].get("response","") or "")}', flush=True)
        re = res.get('rubricEval') or {}
        print(f'  result.rubricEval: score={re.get("score")} met={re.get("metCount")}/{re.get("totalCount")} items={len(re.get("items") or [])}', flush=True)
        if re.get('error'):
            print(f'    rubric.error: {re.get("error")[:100]}', flush=True)
        print(f'  result.response[:80]: {(res.get("response") or "")[:80]}', flush=True)
        print('', flush=True)

    # 3. PROD DB 의 HB-* 시나리오 개수
    all_s = db.get_scenarios()['scenarios']
    hb_count = sum(1 for x in all_s if (x.get('id') or '').startswith('HB-'))
    sample_ids = [x['id'] for x in all_s if (x.get('id') or '').startswith('HB-')][:5]
    print(f'[전체 HB-* 시나리오] {hb_count}건', flush=True)
    print(f'  샘플 ID: {sample_ids}', flush=True)


if __name__ == '__main__':
    main()
