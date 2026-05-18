"""PROD DB의 settings.categories 에 healthbench 항목 추가.

배경: db.py 의 DEFAULT_CATEGORIES 에 healthbench 를 추가했으나, PROD DB 는
이미 사용자 정의 categories 가 settings 테이블에 저장되어 있어 코드 기본값을
덮어쓴다. 일회용 마이그레이션 스크립트로 healthbench 항목만 append.

실행 (Cloud Run Job 으로 PROD 환경에서):
  python scripts/add_healthbench_category.py

  로컬 (Cloud SQL Proxy 통해):
  DATABASE_URL=postgresql://... python scripts/add_healthbench_category.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db


HB_CATEGORY = {
    "id": "healthbench",
    "name": "HealthBench (영문)",
    "prefix": "HB",
    "description": "OpenAI HealthBench 영문 데이터셋 (multi-turn + rubric 평가)",
    "color": "#0ea5e9",
}


def main():
    print('=== healthbench 카테고리 추가 ===', flush=True)

    # 현재 카테고리 조회
    ph = db._p()
    with db.get_conn() as (conn, cur):
        cur.execute(f"SELECT value FROM settings WHERE key = {ph}", ('categories',))
        row = cur.fetchone()

    if row:
        val = row[0] if not isinstance(row, dict) else row.get('value')
        cats = db._pg_json_loads_or(val, list(db.DEFAULT_CATEGORIES))
        source = 'settings.categories (사용자 정의)'
    else:
        cats = list(db.DEFAULT_CATEGORIES)
        source = 'DEFAULT_CATEGORIES (코드)'

    print(f'현재 출처: {source}', flush=True)
    print(f'현재 카테고리 {len(cats)}개:', flush=True)
    for c in cats:
        print(f'  - {c.get("id"):15s} {c.get("name")}', flush=True)

    ids = {c.get('id') for c in cats}
    if 'healthbench' in ids:
        print('\nhealthbench 이미 등록됨 — 변경 없이 종료', flush=True)
        return

    cats.append(HB_CATEGORY)
    db.save_scenario_categories(cats)
    print(f'\nhealthbench 추가 완료 — 총 {len(cats)}개', flush=True)

    # 검증
    final = db.get_categories()
    final_ids = [c.get('id') for c in final]
    print(f'검증 (db.get_categories): {final_ids}', flush=True)
    if 'healthbench' not in final_ids:
        raise SystemExit('FAIL: healthbench 추가 후에도 안 보임 — 저장 실패')


if __name__ == '__main__':
    main()
