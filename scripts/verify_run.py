"""특정 runId 의 batch 결과를 DB 에서 읽어 multi-turn / rubric 메타 검증.

실행:
  VERIFY_RUN_ID=live-verify-20260519-... python scripts/verify_run.py

Cloud Run Job 으로 PROD 검증 시:
  - SCENARIO 별 turnResults / rubricEval 등 핵심 필드를 콘솔에 정리
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db


def main():
    run_id = os.environ.get('VERIFY_RUN_ID', '').strip()
    if not run_id:
        raise SystemExit('VERIFY_RUN_ID env var 가 필요합니다.')

    r = db.get_test_run(run_id)
    if not r:
        print(f'NOT FOUND: {run_id}', flush=True)
        sys.exit(1)

    print(f'== Run: {run_id} ==', flush=True)
    print(f'  status: {r.get("status")}', flush=True)
    print(f'  total: {r.get("total")}  passed: {r.get("passed")}  failed: {r.get("failed")}', flush=True)

    results = r.get('results') or []
    if isinstance(results, str):
        results = json.loads(results)

    print(f'  results: {len(results)}건', flush=True)
    print('', flush=True)

    for res in results:
        sid = res.get('scenarioId', '?')
        print(f'--- {sid} ---', flush=True)
        print(f'  status:       {res.get("status")}', flush=True)
        print(f'  finalSource:  {res.get("finalSource")}', flush=True)
        print(f'  finalScore:   {res.get("finalScore")}', flush=True)
        print(f'  responseLen:  {res.get("responseLength")}', flush=True)
        print(f'  turnsExecuted/Total: {res.get("turnsExecuted")}/{res.get("turnsTotal")}', flush=True)

        tr = res.get('turnResults') or []
        if tr:
            print(f'  turnResults: {len(tr)}개', flush=True)
            for i, t in enumerate(tr):
                err = t.get('error') or ''
                err_str = f' ERR={err[:60]}' if err else ''
                strid = (t.get('conversation_strid') or '')[:18]
                print(
                    f'    turn[{i}]: ms={t.get("elapsed_ms")} '
                    f'http={t.get("http_status")} stopped={t.get("stopped")} '
                    f'first_token_ms={t.get("first_token_ms")} resp_len={len(t.get("response", "") or "")} '
                    f'strid={strid}{err_str}',
                    flush=True,
                )

        rb = res.get('rubricEval')
        if rb:
            print(
                f'  rubricEval:   score={rb.get("score")} '
                f'met={rb.get("metCount")}/{rb.get("totalCount")} '
                f'awarded={rb.get("awardedPoints")}/{rb.get("totalPoints")} '
                f'model={rb.get("model")}',
                flush=True,
            )
            if rb.get('error'):
                print(f'    rubric error: {str(rb.get("error"))[:120]}', flush=True)

        gpt = res.get('gptEval')
        if gpt:
            print(f'  gptEval:      grade={gpt.get("grade")} score={gpt.get("score")} passed={gpt.get("passed")}', flush=True)

        consult = res.get('consultationEval')
        if consult:
            print(f'  consultEval:  totalScore={consult.get("totalScore")} grade={consult.get("grade")}', flush=True)

        err = res.get('error')
        if err:
            print(f'  ERROR:        {str(err)[:200]}', flush=True)

        print('', flush=True)


if __name__ == '__main__':
    main()
