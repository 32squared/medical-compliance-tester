"""옛 batch 식별 + (옵션) 삭제 helper.

기준:
- HB-* 시나리오를 포함하지만 모든 scenarioId 가 현재 scenarios 테이블에 없는 run
  → 시나리오 reset 으로 ID 불일치된 옛 batch
- 또는 사용자 지정 runId 패턴 일치 (e.g., 'live-verify-*' 같은 test batch)

사용:
  # 식별만 (dry-run)
  python scripts/cleanup_old_batches.py
  python scripts/cleanup_old_batches.py --pattern 'live-verify-'
  # 실제 삭제 (재차 확인)
  python scripts/cleanup_old_batches.py --delete --pattern 'live-verify-'
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pattern', default='', help='runId substring 매칭으로 삭제 후보 선별 (예: "live-verify-")')
    ap.add_argument('--orphan-hb', action='store_true',
                    help='현재 DB 에 없는 HB-* scenarioId 만 가진 run 도 삭제 후보로')
    ap.add_argument('--delete', action='store_true',
                    help='실제 삭제 (기본은 dry-run — 식별만)')
    ap.add_argument('--limit', type=int, default=500, help='검사할 run 개수 (최근)')
    args = ap.parse_args()

    print(f'=== cleanup_old_batches (pattern={args.pattern!r} orphan_hb={args.orphan_hb} delete={args.delete}) ===', flush=True)

    # 현재 scenarios 테이블의 HB-* ID
    all_s = db.get_scenarios()['scenarios']
    current_hb_ids = {s['id'] for s in all_s if (s.get('id') or '').startswith('HB-')}
    print(f'현재 DB 의 HB-* scenarios: {len(current_hb_ids)}건', flush=True)

    runs = db.get_test_runs(limit=args.limit)
    print(f'검사 대상 runs: {len(runs)}건', flush=True)
    print('', flush=True)

    candidates = []
    for r in runs:
        rid = r.get('id', '') or ''
        # pattern 매칭
        pattern_match = bool(args.pattern) and args.pattern in rid

        # orphan HB 검사
        orphan = False
        if args.orphan_hb:
            raw = r.get('results') or r.get('results_json')
            if isinstance(raw, str):
                try: results = json.loads(raw)
                except Exception: results = []
            elif isinstance(raw, list):
                results = raw
            else:
                results = []
            hb_ids_in_run = {res.get('scenarioId') for res in results
                             if (res.get('scenarioId') or '').startswith('HB-')}
            if hb_ids_in_run:
                # HB 가 포함된 run — orphan 여부
                orphan_ids = hb_ids_in_run - current_hb_ids
                if hb_ids_in_run and len(orphan_ids) == len(hb_ids_in_run):
                    orphan = True
                    candidates.append({
                        'runId': rid, 'startedAt': r.get('runAt'),
                        'total': r.get('total'),
                        'reason': f'orphan HB ({len(orphan_ids)}건 모두 현재 DB 에 없음)',
                    })
                    continue

        if pattern_match:
            candidates.append({
                'runId': rid, 'startedAt': r.get('runAt'),
                'total': r.get('total'),
                'reason': f'pattern match: {args.pattern}',
            })

    print(f'삭제 후보: {len(candidates)}건', flush=True)
    for c in candidates:
        print(f'  - {c["runId"]:50s} total={c["total"]:4d}  startedAt={c["startedAt"]}  ({c["reason"]})', flush=True)

    if not args.delete:
        print('\n[dry-run] 실제 삭제하려면 --delete 추가', flush=True)
        return

    if not candidates:
        print('\n삭제 대상 없음', flush=True)
        return

    print(f'\n[delete] {len(candidates)}건 삭제 진행', flush=True)
    deleted = 0
    failed = 0
    for c in candidates:
        try:
            db.delete_test_run(c['runId'])
            deleted += 1
        except Exception as e:
            failed += 1
            print(f'  FAIL {c["runId"]}: {e}', flush=True)
    print(f'\n결과: deleted={deleted} failed={failed}', flush=True)


if __name__ == '__main__':
    main()
