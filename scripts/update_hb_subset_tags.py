"""기존 import 된 HB 시나리오의 tags 에 subset:hard / subset:consensus 추가.

배경: 초기 import 시 subset 정보 없었음. Hard / Consensus subset 데이터셋의
prompt_id 와 매칭해서 tags 만 업데이트 (시나리오 재 import 없음, 빠름).

PROD 환경 실행: Cloud Run Job 으로 호출
  python scripts/update_hb_subset_tags.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db
from scripts.import_healthbench import load_subset_ids, _download_one, HARD_PATH, HARD_URL, CONSENSUS_PATH, CONSENSUS_URL


def main():
    print('=== HB 시나리오 subset 태그 업데이트 ===', flush=True)
    print('Hard / Consensus subset 데이터셋 로드 중...', flush=True)
    hard_ids, cons_ids = load_subset_ids()
    print(f'  Hard subset: {len(hard_ids)}건', flush=True)
    print(f'  Consensus subset: {len(cons_ids)}건', flush=True)
    print('', flush=True)

    all_s = db.get_scenarios()['scenarios']
    hb = [s for s in all_s if (s.get('id') or '').startswith('HB-')]
    print(f'DB 내 HB-* 시나리오: {len(hb)}건', flush=True)

    updated = 0
    skipped = 0
    n_hard = 0
    n_cons = 0
    for s in hb:
        gen_info = s.get('generationInfo') or {}
        prompt_id = gen_info.get('prompt_id', '')
        if not prompt_id:
            print(f'  ⚠ prompt_id 없음: {s["id"]}', flush=True)
            skipped += 1
            continue

        current_tags = list(s.get('tags') or [])
        new_tags = [t for t in current_tags if not t.startswith('subset:')]  # 기존 subset 제거
        if prompt_id in hard_ids:
            new_tags.append('subset:hard')
            n_hard += 1
        if prompt_id in cons_ids:
            new_tags.append('subset:consensus')
            n_cons += 1
        new_tags = sorted(set(new_tags))

        if set(new_tags) == set(current_tags):
            skipped += 1
            continue

        db.update_scenario(s['id'], {'tags': new_tags})
        updated += 1

    print(f'\n결과:', flush=True)
    print(f'  업데이트:  {updated}건', flush=True)
    print(f'  변경없음:  {skipped}건', flush=True)
    print(f'  Hard 태그 부여: {n_hard}건', flush=True)
    print(f'  Consensus 태그 부여: {n_cons}건', flush=True)


if __name__ == '__main__':
    main()
