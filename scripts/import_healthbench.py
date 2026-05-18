"""
HealthBench 영문 데이터셋 → 시나리오 import (Phase A.1)

데이터: data/healthbench/oss_eval.jsonl  (5000건, 7 theme)
샘플링: theme별 비율 동일하게 stratified 100건 (seed=42 결정론적)
적재: scenarios 테이블 (category="healthbench", turns_json+rubric_json 포함)

실행:
  # 기본: 100건 import (이미 존재하는 HB-* 는 skip)
  python scripts/import_healthbench.py

  # 기존 HB-* 전체 삭제 후 재import
  python scripts/import_healthbench.py --reset

  # dry-run (DB 변경 없이 분포만 출력)
  python scripts/import_healthbench.py --dry-run

  # 환경변수로 DB 선택 (기본: 로컬 SQLite)
  $env:DATABASE_URL = "postgresql://..."; python scripts/import_healthbench.py
"""
import argparse
import io
import json
import os
import random
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

# Windows 한글 콘솔
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 프로젝트 루트
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import db  # noqa: E402

DATASET_PATH = os.path.join(ROOT, 'data', 'healthbench', 'oss_eval.jsonl')
DATASET_URL = 'https://openaipublic.blob.core.windows.net/simple-evals/healthbench/2025-05-07-06-14-12_oss_eval.jsonl'
DATASET_VERSION = 'healthbench-2025-05-07'
SAMPLE_SIZE = 100
SEED = 42

# 5000건 분포 기반 정수 배분 (합계 100)
STRATIFIED_QUOTA = {
    'global_health':       22,
    'hedging':             21,
    'communication':       18,
    'context_seeking':     12,
    'emergency_referrals': 10,
    'health_data_tasks':   10,
    'complex_responses':    7,
}


def _theme_of(example):
    """example_tags에서 theme:* 태그 1개 추출 (없으면 None)"""
    for t in example.get('example_tags') or []:
        if t.startswith('theme:'):
            return t[len('theme:'):]
    return None


def _phys_cats(example):
    """physician_agreed_category:* 추출"""
    out = []
    for t in example.get('example_tags') or []:
        if t.startswith('physician_agreed_category:'):
            out.append(t[len('physician_agreed_category:'):])
    return out


def _last_user_turn(prompt):
    for m in reversed(prompt):
        if m.get('role') == 'user':
            return m.get('content', '')
    return ''


def _scenario_id(prompt_id):
    """HB-XXXXXXXX (8자리 hex prefix, 대문자)"""
    short = (prompt_id or '').replace('-', '')[:8].upper()
    return f'HB-{short}'


def _risk_level(theme, total_points):
    if theme == 'emergency_referrals':
        return 'HIGH'
    if total_points >= 100:
        return 'HIGH'
    if total_points >= 30:
        return 'MEDIUM'
    return 'LOW'


def _download_dataset():
    """OpenAI 공개 blob storage 에서 dataset 다운로드 → DATASET_PATH 저장."""
    import urllib.request
    print(f'  데이터셋 다운로드: {DATASET_URL}')
    print(f'  대상: {DATASET_PATH}')
    os.makedirs(os.path.dirname(DATASET_PATH), exist_ok=True)
    tmp_path = DATASET_PATH + '.part'
    try:
        with urllib.request.urlopen(DATASET_URL, timeout=300) as resp:
            total = resp.headers.get('Content-Length')
            total_mb = f' ({int(total) / 1024 / 1024:.1f} MB)' if total else ''
            print(f'  HTTP {resp.status}{total_mb} — 다운로드 중...')
            with open(tmp_path, 'wb') as f:
                while True:
                    chunk = resp.read(1 << 20)  # 1 MB
                    if not chunk:
                        break
                    f.write(chunk)
        os.replace(tmp_path, DATASET_PATH)
        size_mb = os.path.getsize(DATASET_PATH) / 1024 / 1024
        print(f'  완료: {size_mb:.1f} MB')
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_dataset():
    if not os.path.exists(DATASET_PATH):
        # 컨테이너/CI 환경: 자동 다운로드 시도
        try:
            _download_dataset()
        except Exception as e:
            raise SystemExit(
                f'데이터셋 다운로드 실패: {e}\n'
                f'  수동 다운로드: curl -sSL -o "{DATASET_PATH}" "{DATASET_URL}"'
            )
    items = []
    with open(DATASET_PATH, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            items.append(json.loads(line))
    return items


def stratified_sample(items, seed=SEED):
    """theme별로 STRATIFIED_QUOTA 만큼 결정론적 샘플링"""
    by_theme = defaultdict(list)
    skipped = 0
    for it in items:
        t = _theme_of(it)
        if t is None:
            skipped += 1
            continue
        by_theme[t].append(it)

    rng = random.Random(seed)
    sampled = []
    for theme, quota in STRATIFIED_QUOTA.items():
        pool = by_theme.get(theme, [])
        if len(pool) < quota:
            raise SystemExit(f'theme={theme} 풀 부족: pool={len(pool)} quota={quota}')
        # 결정론적: prompt_id로 정렬 후 샘플
        pool_sorted = sorted(pool, key=lambda d: d.get('prompt_id', ''))
        sampled.extend(rng.sample(pool_sorted, quota))

    if skipped:
        print(f'  (참고: theme 태그 없는 {skipped}건은 제외)')
    return sampled


def to_scenario(example):
    """HealthBench 예제 → scenarios 테이블 row 데이터"""
    pid = example.get('prompt_id', '')
    prompt_msgs = example.get('prompt') or []
    rubrics = example.get('rubrics') or []
    theme = _theme_of(example) or 'unknown'
    phys_cats = _phys_cats(example)
    total_points = sum(float(r.get('points', 0) or 0) for r in rubrics if (r.get('points') or 0) > 0)

    last_user = _last_user_turn(prompt_msgs)
    # CHECK(length(prompt) <= 5000) 안전장치 (실측 최대 2792자라 미발동)
    if len(last_user) > 5000:
        last_user = last_user[:4990] + '…[trunc]'

    n_turns = len(prompt_msgs)
    tags = sorted(set(phys_cats + [
        f'theme:{theme}',
        f'turns:{n_turns}',
        'healthbench',
        'lang:en',
    ]))

    return {
        'id': _scenario_id(pid),
        'category': 'healthbench',
        'subcategory': theme,
        'prompt': last_user,
        'expectedBehavior': '',
        'shouldRefuse': False,
        'riskLevel': _risk_level(theme, total_points),
        'tags': tags,
        'enabled': True,
        'source': DATASET_VERSION,
        'turns': prompt_msgs,
        'rubric': rubrics,
        'generationInfo': {
            'origin': 'healthbench',
            'dataset_version': DATASET_VERSION,
            'prompt_id': pid,
            'theme': theme,
            'physician_agreed_categories': phys_cats,
            'rubric_count': len(rubrics),
            'rubric_max_total_points': total_points,
            'turn_count': n_turns,
        },
    }


def reset_existing():
    """기존 HB-* 시나리오 전체 삭제"""
    ph = db._p()
    with db.get_conn() as (conn, cur):
        cur.execute(f"SELECT id FROM scenarios WHERE id LIKE {ph}", ('HB-%',))
        ids = [r[0] if not isinstance(r, dict) else r['id'] for r in cur.fetchall()]
    if not ids:
        print('  (기존 HB-* 시나리오 없음)')
        return 0
    db.delete_scenarios_bulk(ids)
    print(f'  기존 HB-* {len(ids)}건 삭제')
    return len(ids)


def existing_hb_ids():
    ph = db._p()
    with db.get_conn() as (conn, cur):
        cur.execute(f"SELECT id FROM scenarios WHERE id LIKE {ph}", ('HB-%',))
        return {(r[0] if not isinstance(r, dict) else r['id']) for r in cur.fetchall()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reset', action='store_true', help='기존 HB-* 시나리오 삭제 후 재import')
    ap.add_argument('--dry-run', action='store_true', help='DB 변경 없이 분포만 출력')
    ap.add_argument('--limit', type=int, default=SAMPLE_SIZE, help='샘플 크기 (기본 100, 디버그용)')
    args = ap.parse_args()

    print(f'== HealthBench import (Phase A.1) ==')
    print(f'데이터셋: {DATASET_PATH}')
    print(f'버전: {DATASET_VERSION}  /  seed={SEED}')

    items = load_dataset()
    print(f'전체 examples: {len(items)}')

    # 전체 분포 검증
    theme_counts = Counter(_theme_of(it) for it in items)
    print('\n전체 theme 분포:')
    for t, n in theme_counts.most_common():
        if t is None:
            continue
        target = STRATIFIED_QUOTA.get(t, 0)
        print(f'  {t:25s}  pool={n:5d}  -> sample={target}')

    sampled = stratified_sample(items, seed=SEED)
    print(f'\n샘플 합계: {len(sampled)}')

    scenarios = [to_scenario(ex) for ex in sampled]

    # 샘플 통계
    samp_theme = Counter(s['subcategory'] for s in scenarios)
    samp_risk = Counter(s['riskLevel'] for s in scenarios)
    samp_turns = Counter(len(s['turns']) for s in scenarios)
    samp_rubric = sum(len(s['rubric']) for s in scenarios)

    print('\n샘플 theme 분포:')
    for t in sorted(samp_theme):
        print(f'  {t:25s}  {samp_theme[t]}')
    print('\n샘플 risk_level:', dict(samp_risk))
    print('샘플 turn count:', dict(sorted(samp_turns.items())))
    print(f'샘플 rubric 합계: {samp_rubric}건 (avg {samp_rubric/len(scenarios):.1f}/건)')

    if args.dry_run:
        print('\n--dry-run: DB 변경 없이 종료')
        sample_id = scenarios[0]['id']
        print(f'\n예시 시나리오 ID: {sample_id}')
        print(f'  prompt (last_user): {scenarios[0]["prompt"][:200]}...')
        print(f'  turns: {len(scenarios[0]["turns"])} messages')
        print(f'  rubric: {len(scenarios[0]["rubric"])} items')
        return

    # DB 적재
    if args.reset:
        print('\n[reset] 기존 HB-* 삭제 중...')
        reset_existing()

    skip_ids = existing_hb_ids() if not args.reset else set()
    inserted = 0
    skipped = 0
    failed = 0

    print(f'\n[insert] {len(scenarios)}건 적재 시작 (skip 기존={len(skip_ids)}건)')
    for s in scenarios:
        if s['id'] in skip_ids:
            skipped += 1
            continue
        try:
            db.create_scenario(s)
            inserted += 1
        except Exception as e:
            failed += 1
            print(f'  FAIL {s["id"]}: {e}', file=sys.stderr)

    print(f'\n결과: inserted={inserted}  skipped={skipped}  failed={failed}')

    # 적재 후 검증
    final_ids = existing_hb_ids()
    print(f'DB 내 HB-* 시나리오 총: {len(final_ids)}건')


if __name__ == '__main__':
    main()
