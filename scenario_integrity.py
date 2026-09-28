# -*- coding: utf-8 -*-
"""PHR 문항 적재 전 무결성 검사 — 문항이 연결된 사람의 기록과 맞는지 본다.

2026-09-22 에 문항 생성기와 운영 DB 의 케이스 번호가 달라 350문항 중 305문항이 다른 사람의
기록으로 답변된 일이 있었다. 적재 경로(scripts/seed_scenarios_json.py · POST /api/scenarios/import)가
이 검사를 먼저 돌리고, error 가 하나라도 있으면 적재하지 않는다.

검사 (문항 1건 × 연결 케이스 1건):
  case_missing        error  phrCaseId 가 phr_cases 에 없음
  expected_value      error  기대 답변(expectedBehavior)의 수치+단위가 기록 어디에도 없음
  exam_missing        error  질문이 묻는 암검진 종류가 기록에 없음
  rx_missing          warn   처방·복용약을 묻는데 처방 기록이 0건 (결측 안내를 보는 문항일 수 있음)
예외: tags 에 'expect:missing' 이 있으면 exam_missing·rx_missing 을 보지 않는다(없음을 묻는 문항).
"""
import json
import re

CANCER_EXAMS = ('위암', '대장암', '유방암', '자궁경부암', '간암', '폐암')
_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(mg/dL|mmHg|cm|kg|%|U/L|IU/L|g/dL|mL/min|㎎/㎗|kg/m2|kg/㎡)")
_RX_Q = re.compile(r"처방|복용|먹고 있는 약|약 이름|먹는 약")


def _case_of(row):
    if not row:
        return None
    c = row.get('case') if isinstance(row, dict) else None
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except ValueError:
            c = None
    return c if isinstance(c, dict) else (row if isinstance(row, dict) and 'checkups' in row else None)


def _num_in(blob, n):
    """기록 JSON 안에 수치가 있는가. 184 와 184.0 을 같게 본다."""
    if n in blob:
        return True
    try:
        f = float(n)
    except ValueError:
        return False
    alts = {f"{f:g}", f"{f:.1f}", f"{int(f)}" if f.is_integer() else f"{f:g}"}
    return any(re.search(r"(?<![\d.])" + re.escape(a) + r"(?![\d])", blob) for a in alts)


def check_row(sc, case):
    """문항 1건 → 문제 목록 [{id, code, severity, detail}]."""
    sid = sc.get('id')
    tags = sc.get('tags') or []
    out = []

    def add(code, sev, detail):
        out.append({'id': sid, 'case': sc.get('phrCaseId'), 'code': code, 'severity': sev, 'detail': detail})

    if case is None:
        add('case_missing', 'error', 'phr_cases 에 케이스 없음')
        return out
    blob = json.dumps(case, ensure_ascii=False)
    for n, unit in _NUM.findall(sc.get('expectedBehavior') or ''):
        if not _num_in(blob, n):
            add('expected_value', 'error', f'기대 답변의 {n}{unit} 이(가) 기록에 없음')
    if 'expect:missing' in tags:
        return out
    q = sc.get('prompt') or ''
    have = {str(x.get('exam') or '') for x in ((case.get('checkups') or {}).get('cancer') or []) if isinstance(x, dict)}
    for e in CANCER_EXAMS:
        if e in q and not any(e in h for h in have):
            add('exam_missing', 'error', f'질문이 {e} 검진을 묻는데 기록에 없음(기록: {sorted(have) or "없음"})')
    if _RX_Q.search(q):
        n_rx = (case.get('counts') or {}).get('prescription')
        if n_rx is None:
            n_rx = len(case.get('prescriptions') or [])
        if not n_rx:
            add('rx_missing', 'warn', '처방·복용약을 묻는데 처방 기록 0건')
    return out


def check_rows(rows, get_case):
    """문항 목록 → (errors, warnings). get_case(case_id) 는 phr_cases 행(또는 케이스 dict)이나 None."""
    cache, errors, warns = {}, [], []
    for sc in rows or []:
        cid = sc.get('phrCaseId')
        if not cid:
            continue
        if cid not in cache:
            try:
                cache[cid] = _case_of(get_case(cid))
            except Exception:
                cache[cid] = None
        for p in check_row(sc, cache[cid]):
            (errors if p['severity'] == 'error' else warns).append(p)
    return errors, warns


def summarize(problems, limit=10):
    by = {}
    for p in problems:
        by[p['code']] = by.get(p['code'], 0) + 1
    return {'counts': by, 'examples': problems[:limit]}
