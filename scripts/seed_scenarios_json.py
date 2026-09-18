#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""시나리오 JSON 적재 — 호스트 import 형식({"scenarios": [...]} 또는 리스트)을 DB 에 넣는다.

같은 id 가 있으면 덮어쓴다(--no-replace 면 건너뜀). 여러 번 돌려도 결과는 같다.
콘솔에는 id·건수만 찍는다(문항 본문·케이스 값은 출력하지 않는다).

실행:
    python scripts/seed_scenarios_json.py --file scripts/scenarios_v18_regression.json [--dry-run] [--no-replace]
Cloud Run Job:
    RUN_MODE=seed_scenarios SEED_SCENARIOS_JSON=/app/scripts/scenarios_v18_regression.json  (entrypoint.sh)

Cloud SQL 이 private IP 라 로컬에서 운영 DB 에 직접 넣을 수 없어 Job 으로 돌린다
(scripts/seed_advisory.py · seed_phr_batch.py 와 같은 경로).
"""
import argparse
import json
import os
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402

#: db.create_scenario() 가 받는 키. 그 밖의 키(_meta 등)는 버린다.
ALLOWED = {
    'id', 'category', 'subcategory', 'prompt', 'expectedBehavior', 'shouldRefuse', 'riskLevel',
    'tags', 'enabled', 'source', 'parentId', 'generationInfo', 'sourceConversationId',
    'followUps', 'turns', 'rubric', 'phrCaseId', 'phrVitals', 'branch', 'symptomKey',
}


def load(path):
    with open(path, encoding='utf-8') as f:
        raw = json.load(f)
    items = raw if isinstance(raw, list) else (raw or {}).get('scenarios') or []
    out = []
    for it in items:
        if not isinstance(it, dict) or not it.get('id') or not it.get('prompt'):
            continue
        out.append({k: v for k, v in it.items() if k in ALLOWED})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--file', default=os.environ.get('SEED_SCENARIOS_JSON', ''))
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--no-replace', action='store_true', help='같은 id 가 있으면 덮어쓰지 않고 건너뛴다')
    args = ap.parse_args()
    if not args.file or not os.path.isfile(args.file):
        print(f'[seed_scenarios] 파일 없음: {args.file!r}')
        return 2

    rows = load(args.file)
    print(f'[seed_scenarios] {os.path.basename(args.file)} → {len(rows)}건  ids={[r["id"] for r in rows]}')
    if args.dry_run:
        print('[seed_scenarios] dry-run — 저장하지 않음')
        return 0

    db.init_db()
    created = replaced = skipped = 0
    for r in rows:
        r.setdefault('enabled', True)
        existing = db.get_scenario(r['id'])
        if existing and args.no_replace:
            skipped += 1
            continue
        if existing:
            db.delete_scenario(r['id'])
            replaced += 1
        else:
            created += 1
        db.create_scenario(r)
    print(f'[seed_scenarios] 완료 — 신규 {created} · 교체 {replaced} · 건너뜀 {skipped}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
