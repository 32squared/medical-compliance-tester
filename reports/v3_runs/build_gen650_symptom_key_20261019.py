# -*- coding: utf-8 -*-
"""일반 650 시나리오의 증상군 키(symptom_key) 초안 표 + 사람 검수 표 생성기 (2026-10-19).

배경: 10/16 DEV 일반 650 판정(run gen650-dev-20261016T063907)의 C 이하 감사(DOC-T6VZ4)에서 SV-02·03·04 거짓
미충족 상당수가 증상군 오분류에서 나왔다 — 650 문항에 symptomKey 가 없어 판정기 match_group 이 질문 낱말의
글자 수로 증상군을 추측하기 때문(REQ-IEZO 회신). 정식 경로는 호스트가 symptomKey 를 주는 것이고, 42군 밖은
"none" 으로 주면 SV-02~04 가 na 다(사용자 결정 ② 2026-10-19).

입력
  --sample     scripts/samples/general650_seed20261016.json (650 id 순서)
  --dump       10/16 run 의 호스트 DB 덤프(results_json 에 scenarioId·prompt·tags·evalV3.checklist) — 저장소 밖
  --labels     reports/v3_runs/gen650_symptom_key_labels_20261019.txt (id|key|confidence|근거, Claude 가 질문을 읽고 분류)
  --checklists packages/medical_shared/compliance_rules/consultation_checklists.json (42군)
  --inventory  (선택) reports/v3_runs/dumps/inv_phr350.json 의 2026-09-29 재고 분류(cls.symptom_key) — 참고 열

출력
  reports/v3_runs/gen650_symptom_key_20261019.json — 650건 전부: 최종 symptom_key, 신뢰도, 근거, match_group 상위 3 후보·
      1위(판정기 코드 그대로), 10/16 실행에서 실제 쓰인 증상군, 태그 symptom:, 재고 분류, 일치 여부. 적용 스크립트가 읽는다.
  reports/v3_runs/gen650_symptom_key_review_20261019.md — match_group 1위와 다르거나 신뢰도 low 인 건만 모은 사람 검수 표.

match_group 은 packages/medical_eval(서브모듈)의 코드를 그대로 부른다 — 보고서 생성기이므로 경계검사(--forbid eval) 대상
호스트 모듈이 아니다. LLM 호출은 없다.

    python reports/v3_runs/build_gen650_symptom_key_20261019.py --dump <gen650 덤프.json> [--inventory <inv_phr350.json>]
"""
import argparse
import collections
import io
import json
import os
import sys
from datetime import datetime, timezone

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
sys.path.insert(0, os.path.join(ROOT, 'packages', 'medical_eval', 'src'))

from medical_eval import validity_symptom as vs  # noqa: E402


def load_labels(path):
    out = {}
    for ln in open(path, encoding='utf-8'):
        ln = ln.rstrip('\n')
        if not ln or ln.startswith('#'):
            continue
        sid, key, conf, note = ln.split('|', 3)
        out[sid] = {'symptom_key': key, 'confidence': conf, 'note': note}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--sample', default=os.path.join(ROOT, 'scripts', 'samples', 'general650_seed20261016.json'))
    ap.add_argument('--dump', required=True)
    ap.add_argument('--labels', default=os.path.join(HERE, 'gen650_symptom_key_labels_20261019.txt'))
    ap.add_argument('--checklists', default=os.path.join(ROOT, 'packages', 'medical_shared', 'compliance_rules',
                                                         'consultation_checklists.json'))
    ap.add_argument('--inventory', default=None)
    ap.add_argument('--db-current', default=os.path.join(HERE, 'gen650_symptom_key_prod_before_20261019.json'),
                    help='적용 전 운영 DB 의 symptomKey 스냅숏(items[id].symptomKey). 있으면 "기존 값과 다른 건" 절을 만든다')
    ap.add_argument('--out-json', default=os.path.join(HERE, 'gen650_symptom_key_20261019.json'))
    ap.add_argument('--out-md', default=os.path.join(HERE, 'gen650_symptom_key_review_20261019.md'))
    a = ap.parse_args(argv)

    cls = vs.load_checklists(a.checklists)
    assert len(cls) == 42, len(cls)
    valid = {g['symptom_key'] for g in cls}
    name_of = {g['symptom_key']: g['symptom_name'] for g in cls}
    name_of['none'] = '없음(42군 밖·증상 없음)'
    name2key = {g['symptom_name'].replace(' ', ''): g['symptom_key'] for g in cls}
    name2key['호흡성흉통'] = 'chest_pain_resp'

    ids = json.load(open(a.sample, encoding='utf-8'))['ids']
    dump = json.load(open(a.dump, encoding='utf-8'))
    byid = {r['scenarioId']: r for r in dump['results_json']}
    labels = load_labels(a.labels)
    inv = {}
    if a.inventory and os.path.isfile(a.inventory):
        for r in json.load(open(a.inventory, encoding='utf-8'))['rows']:
            c = r.get('cls') or {}
            inv[r['id']] = c.get('symptom_key') if isinstance(c, dict) else None

    dbcur = {}
    if a.db_current and os.path.isfile(a.db_current):
        dbcur = {k: (v.get('symptomKey') if isinstance(v, dict) else v) or None
                 for k, v in json.load(open(a.db_current, encoding='utf-8'))['items'].items()}

    items = []
    for sid in ids:
        r = byid[sid]
        lab = labels[sid]
        assert lab['symptom_key'] in valid or lab['symptom_key'] == 'none', (sid, lab)
        prompt = r.get('prompt') or ''
        text = vs._norm(prompt)
        scored = sorted(((vs._score_group(g, text), g['symptom_key']) for g in cls), key=lambda p: p[0], reverse=True)
        top3 = [{'symptom_key': k, 'score': s} for s, k in scored[:3] if s > 0]
        mg = vs.match_group(prompt, cls)
        mg_pick = mg['symptom_key'] if mg else None
        ck = (r.get('evalV3') or {}).get('checklist') or {}
        tags = r.get('tags') or []
        tagsym = next((t.split(':', 1)[1] for t in tags if isinstance(t, str) and t.startswith('symptom:')), None)
        items.append({
            'id': sid, 'category': r.get('category'), 'subcategory': r.get('subcategory'),
            'prompt_summary': ' '.join(prompt.split())[:80],
            'symptom_key': lab['symptom_key'], 'symptom_name': name_of[lab['symptom_key']],
            'confidence': lab['confidence'], 'note': lab['note'],
            'mg_top3': top3, 'mg_pick': mg_pick,
            'run_used': ck.get('symptom_key'),
            'tag_symptom_key': name2key.get((tagsym or '').replace(' ', '')) if tagsym else None,
            'inventory_cls': inv.get(sid),
            'db_before': dbcur.get(sid),
            'agree_mg': (mg_pick == lab['symptom_key']) or (mg_pick is None and lab['symptom_key'] == 'none'),
        })

    dist = collections.Counter(it['symptom_key'] for it in items)
    conf = collections.Counter(it['confidence'] for it in items)

    # 검수 대상: 코드 폴백(match_group 1위)이 다른 군을 골랐거나, 10/16 실행이 실제로 다른 군으로 채점했거나,
    # Claude 가 자신 없다(low)고 표시한 건. match_group 이 None(못 고름)인 것은 충돌이 아니라 '지정 없음'이므로 넣지 않는다.
    def conflict(it):
        return ((it['mg_pick'] and it['mg_pick'] != it['symptom_key'])
                or (it['run_used'] and it['run_used'] != it['symptom_key']))
    review = [it for it in items if conflict(it) or it['confidence'] == 'low']
    db_conflict = [it for it in items if it['db_before'] and it['db_before'] != it['symptom_key']]
    summary = {
        'n': len(items), 'none': dist.get('none', 0),
        'by_key': {k: dist[k] for k in sorted(dist, key=lambda k: (-dist[k], k))},
        'confidence': dict(conf),
        'agree_with_match_group': sum(1 for it in items if it['agree_mg']),
        'match_group_none': sum(1 for it in items if it['mg_pick'] is None),
        'match_group_conflict': sum(1 for it in items if it['mg_pick'] and it['mg_pick'] != it['symptom_key']),
        'run_used_none': sum(1 for it in items if not it['run_used']),
        'run_used_conflict': sum(1 for it in items if it['run_used'] and it['run_used'] != it['symptom_key']),
        'db_before_set': sum(1 for it in items if it['db_before']),
        'db_before_same': sum(1 for it in items if it['db_before'] and it['db_before'] == it['symptom_key']),
        'db_before_conflict': len(db_conflict),
        'review_rows': len(review),
    }
    json.dump({'generatedAt': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'source_run': dump.get('id'), 'sample': os.path.basename(a.sample),
               'labels': os.path.basename(a.labels), 'summary': summary, 'items': items},
              open(a.out_json, 'w', encoding='utf-8'), ensure_ascii=False, indent=1)

    L = []
    L.append('# 일반 650 시나리오 증상군 키(symptom_key) — 사람 검수 표 (2026-10-19)\n')
    L.append('판정기(medical_eval) 가 질문 낱말로 증상군을 추측하지 않도록 650 문항 전부에 `symptomKey` 를 명시한다(REQ-IEZO 호스트 결정 ②). '
             '값은 42군 키 또는 `none`(주소(主訴)가 42군 밖이거나 증상이 없는 문항 → SV-02·03·04 na).\n')
    L.append('분류 방법: (a) 판정기 `validity_symptom.match_group` 의 코드 점수(상위 3 후보, 1위) · (b) Claude 가 질문 본문을 읽고 주소 1개를 고름. '
             '원인 언급("스트레스 때문인지")·부수 증상("잠을 못 자요")·부위 낱말("허리 옆")은 주소가 아니다. '
             '전체 표는 `gen650_symptom_key_20261019.json`, 라벨 원본은 `gen650_symptom_key_labels_20261019.txt`.\n')
    L.append('## 요약\n')
    L.append(f'- 650건 전부 키 있음 · none {summary["none"]}건 · 신뢰도 high {conf["high"]} / med {conf["med"]} / low {conf["low"]}')
    L.append(f'- match_group 1위와 일치 {summary["agree_with_match_group"]}건 · match_group 이 None(못 고름)인 문항 {summary["match_group_none"]}건 · '
             f'match_group 1위가 다른 군인 문항 {summary["match_group_conflict"]}건')
    L.append(f'- 10/16 실행(run gen650-dev-20261016T063907)에서 증상군 없이 판정된 문항 {summary["run_used_none"]}건 · '
             f'다른 군으로 채점된 문항 {summary["run_used_conflict"]}건')
    L.append(f'- **검수 대상 {len(review)}건** = match_group 1위가 다른 군 ∪ 10/16 실행이 다른 군 ∪ 신뢰도 low. '
             'match_group 이 None 인 것은 충돌이 아니라 지정 없음이라 넣지 않았다. '
             '아래 표에서 `Claude 선택` 열을 고치면 라벨 파일을 바꾸고 생성기를 다시 돌린다.\n')
    if dbcur:
        L.append(f'- 적용 전 운영 DB 에 이미 키가 있던 문항 {summary["db_before_set"]}건(2026-09-29 재고 분류가 들어간 값) · '
                 f'그중 Claude 선택과 같음 {summary["db_before_same"]}건 · **다름 {summary["db_before_conflict"]}건**(아래 별도 절, 적용 스크립트는 `--force` 없이는 덮지 않는다)\n')
    L.append('## 군별 분포\n')
    L.append('| 키 | 이름 | 건수 |\n|---|---|---|')
    for k, n in summary['by_key'].items():
        L.append(f'| {k} | {name_of[k]} | {n} |')
    L.append('')
    L.append('## 검수 대상\n')
    L.append('`match_group 1위` 는 현재 판정기 코드(sv-v2)의 폴백이 고르는 군, `10/16 실행` 은 실제 run 의 checklist.symptom_key'
             '(판정기 판이 달라 match_group 1위와 다를 수 있다). '
             '`태그` 는 옛 시나리오의 `symptom:` 태그, `재고 9/29` 는 inv_phr350.json 의 LLM 분류(참고). `일치` 는 Claude 선택 = match_group 1위.\n')
    L.append('| # | scenario_id | 질문 요약 | match_group 1위 (상위 3·점수) | 10/16 실행 | 태그 | 재고 9/29 | Claude 선택 | 신뢰도 | 일치 | 근거 |')
    L.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for n, it in enumerate(review, 1):
        top = ', '.join(f"{t['symptom_key']}:{t['score']}" for t in it['mg_top3']) or '—'
        q = it['prompt_summary'].replace('|', '｜')
        L.append(f"| {n} | {it['id']} | {q} | {it['mg_pick'] or '—'} ({top}) | {it['run_used'] or '—'} | {it['tag_symptom_key'] or '—'} | "
                 f"{it['inventory_cls'] or '—'} | **{it['symptom_key']}** | {it['confidence']} | {'○' if it['agree_mg'] else '✗'} | {it['note'].replace('|', '｜')} |")
    L.append('')
    if dbcur:
        L.append('## 운영 DB 기존 값과 다른 건\n')
        L.append('9/29 재고 분류로 들어간 값과 이번 읽기가 다른 문항. 사람이 `Claude 선택` 을 확정하면 '
                 '`python scripts/apply_symptom_key_gen650_20261019.py --env prod --force` 로 덮어쓴다(되돌릴 값은 `gen650_symptom_key_prod_before_20261019.json`).\n')
        L.append('사용자 결정(2026-10-19): 처음 36건 중 두 군 사이 판단이던 14건(DIAG-023·094·161·202, EMER-040·083·146·275, GENE-007·044·130, '
                 'PRES-018, TREA-011, 감각기관-003)은 운영 기존 값으로 되돌렸고, 임신 출혈·외음부 5건(EMER-200·251·252, TREA-102, 비뇨생식-009)은 '
                 '복통군 체크리스트에 임신·출혈 항목이 없어 none 으로 정했다. **EMER-037**(돌발성 청력 저하·이명)은 운영 기존 값 vision_loss 가 '
                 '명백히 틀려 되돌리지 않고 ear_pain 을 유지한다. 남은 건은 none 또는 다른 군이 분명한 것이다.\n')
        L.append('| # | scenario_id | 질문 요약 | DB 기존 값 | Claude 선택 | 신뢰도 | 근거 |\n|---|---|---|---|---|---|---|')
        for n, it in enumerate(db_conflict, 1):
            L.append(f"| {n} | {it['id']} | {it['prompt_summary'].replace('|', '｜')} | {it['db_before']} | **{it['symptom_key']}** | "
                     f"{it['confidence']} | {it['note'].replace('|', '｜')} |")
        L.append('')
    L.append('## 전체 650건 (요약)\n')
    L.append('| scenario_id | Claude 선택 | 신뢰도 | match_group 1위 | 10/16 실행 | DB 기존 값 |\n|---|---|---|---|---|---|')
    for it in items:
        L.append(f"| {it['id']} | {it['symptom_key']} | {it['confidence']} | {it['mg_pick'] or '—'} | {it['run_used'] or '—'} | {it['db_before'] or '—'} |")
    open(a.out_md, 'w', encoding='utf-8').write('\n'.join(L) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f'[build] json → {a.out_json}\n[build] md   → {a.out_md}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
