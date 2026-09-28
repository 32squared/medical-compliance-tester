# -*- coding: utf-8 -*-
"""시나리오 사용 여부를 한꺼번에 바꾼다 (Cloud Run Job RUN_MODE=set_scenarios_enabled 용).

운영 DB 는 private IP 라 로컬에서 닿지 않는다. 지우지 않고 enabled 만 바꾸며, --tag 를 주면 이유를
태그로 남긴다(되돌릴 때 같은 태그로 찾는다). --expect 로 대상 건수를 못 박아 조건이 틀렸을 때 멈춘다.

예) 케이스 번호가 틀린 기존 PHR 350건(2026-09-22 확인) 끄기:
    python scripts/set_scenarios_enabled.py --category phr_case --id-prefix PHRQ-B --enabled 0 \
        --expect 350 --tag retired:case-misnumbered-20260922 [--dry-run]
"""
import argparse
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _all(db):
    """db.get_scenarios() 는 scenarios.json 형식({'scenarios': [...]}) 을 돌려준다."""
    data = db.get_scenarios()
    return data.get('scenarios') or [] if isinstance(data, dict) else list(data or [])


def select(rows, *, category='', id_prefix=''):
    return [r for r in rows
            if (not category or r.get('category') == category)
            and (not id_prefix or str(r.get('id') or '').startswith(id_prefix))]


def apply(*, category='', id_prefix='', enabled=False, expect=None, tag='', dry_run=False, db=None,
          log=print):
    if db is None:
        import db as db  # noqa: F811
    if not category and not id_prefix:
        log('[set_enabled] --category 나 --id-prefix 중 하나는 필요합니다')
        return 2
    rows = select(_all(db), category=category, id_prefix=id_prefix)
    todo = [r for r in rows if bool(r.get('enabled', True)) != enabled or (tag and tag not in (r.get('tags') or []))]
    log(f'[set_enabled] 조건 category={category!r} id_prefix={id_prefix!r} → {len(rows)}건, 바꿀 것 {len(todo)}건 '
        f'(enabled→{int(enabled)} tag={tag!r})')
    if expect is not None and len(rows) != expect:
        log(f'[set_enabled] 대상 {len(rows)}건이 --expect {expect} 와 달라 중단')
        return 3
    if rows:
        log(f'[set_enabled] 예: {[r["id"] for r in rows[:5]]} … {[r["id"] for r in rows[-2:]]}')
    if dry_run:
        log('[set_enabled] dry-run: 저장하지 않음')
        return 0
    for r in todo:
        data = {'enabled': enabled}
        if tag and tag not in (r.get('tags') or []):
            data['tags'] = list(r.get('tags') or []) + [tag]
        db.update_scenario(r['id'], data)
    after = select(_all(db), category=category, id_prefix=id_prefix)
    n_on = sum(1 for r in after if r.get('enabled', True))
    log(f'[set_enabled] 저장 확인: 대상 {len(after)}건 중 enabled={n_on}')
    return 0 if all(bool(r.get('enabled', True)) == enabled for r in after) else 4


def main(argv=None):
    env = os.environ.get
    ap = argparse.ArgumentParser()
    ap.add_argument('--category', default=env('SET_CATEGORY', ''))
    ap.add_argument('--id-prefix', default=env('SET_ID_PREFIX', ''))
    ap.add_argument('--enabled', default=env('SET_ENABLED', '0'), choices=['0', '1'])
    ap.add_argument('--expect', type=int, default=int(env('SET_EXPECT')) if env('SET_EXPECT') else None)
    ap.add_argument('--tag', default=env('SET_TAG', ''))
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args(argv)
    return apply(category=a.category, id_prefix=a.id_prefix, enabled=a.enabled == '1', expect=a.expect,
                 tag=a.tag, dry_run=a.dry_run)


if __name__ == '__main__':
    sys.exit(main())
