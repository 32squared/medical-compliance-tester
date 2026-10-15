# -*- coding: utf-8 -*-
"""mhc-viz 시각 블록 — 추출·검증·평가용 치환.

규약: docs/mhc_viz_convention_v1_20261014.html (스키마 docs/mhc-viz.schema.json).
답변 본문(마크다운) 안의 ```mhc-viz 펜스 블록 하나가 시각 하나다. 이 모듈은
  · iter_blocks(text)      — 닫힌 블록과 닫히지 않은 블록을 찾는다
  · validate_block(obj)    — 스키마(jsonschema 가 있으면) + 스키마 밖 규칙 → 문제 목록
  · check_answer(text)     — 답변 하나의 형식 검사 결과(dict)
  · strip_blocks(text)     — 평가기 입력용: 블록을 "[표: caption]" 한 줄로 바꾼다(텍스트 등가 원칙)
LLM 호출 없음. 호스트(proxy_server)와 CLI(scripts/mhc_viz_check.py)가 같이 쓴다.
"""
from __future__ import annotations

import json
import os
import re

FENCE_RE = re.compile(r'```mhc-viz[ \t]*\r?\n([\s\S]*?)\r?\n```')
OPEN_RE = re.compile(r'```[ 	]*([A-Za-z_-]*mhc[A-Za-z_-]*)', re.I)
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
CITE_RE = re.compile(r'^\[\d+:\d+\]$')

KINDS = ('table', 'line', 'range', 'timeline')
POSITIONS = ('in', 'border', 'above', 'below')
DATA_SOURCES = ('phr.checkup', 'phr.oral', 'phr.cancer', 'phr.prescription', 'conversation', 'literature')
POSITION_KO = {'in': '범위 안', 'border': '경계', 'above': '기준 위', 'below': '기준 아래'}

MAX_BLOCKS = 3
MAX_BYTES = 4096
#: title·caption 에 쓰지 않는 낱말 — 기준 비교로만 서술한다(규약 6.2). 구간 라벨(bands[].label)은 제외.
BANNED_WORDS = ('진단', '비만입니다', '당뇨입니다', '지방간입니다', '고혈압입니다', '병입니다', '위험합니다', '처방하', '처방받', '복용하세요')

_SCHEMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'docs', 'mhc-viz.schema.json')
_schema_cache = None


def load_schema():
    global _schema_cache
    if _schema_cache is None:
        with open(_SCHEMA_PATH, encoding='utf-8') as f:
            _schema_cache = json.load(f)
    return _schema_cache


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def iter_blocks(text):
    """닫힌 블록 목록과 닫히지 않은 블록(있으면) 을 돌려준다.

    return (closed, unclosed) — closed: [{'start','end','json'}], unclosed: {'start','json'} | None
    """
    if not text:
        return [], None
    closed = [{'start': m.start(), 'end': m.end(), 'json': m.group(1)} for m in FENCE_RE.finditer(text)]
    last_end = closed[-1]['end'] if closed else 0
    rest = text[last_end:]
    idx = rest.find('```mhc-viz')
    unclosed = None
    if idx >= 0:
        unclosed = {'start': last_end + idx, 'json': rest[idx + len('```mhc-viz'):].strip()}
    return closed, unclosed


def _schema_issues(obj):
    """jsonschema 가 있으면 스키마 검사. 없으면 빈 목록(스키마 밖 규칙만 검사)."""
    try:
        import jsonschema  # noqa: WPS433
    except Exception:
        return []
    validator = jsonschema.Draft202012Validator(load_schema())
    out = []
    for err in sorted(validator.iter_errors(obj), key=lambda e: list(e.path)):
        path = '/'.join(str(p) for p in err.path) or '(root)'
        out.append(f'스키마 {path}: {err.message}'[:160])
    return out


def validate_block(obj, raw_json=None):
    """블록 객체 하나의 문제 목록(빈 목록이면 통과). 스키마 + 스키마 밖 규칙."""
    issues = []
    if raw_json is not None and len(raw_json.encode('utf-8')) > MAX_BYTES:
        issues.append(f'블록 {MAX_BYTES}바이트 초과')
    if not isinstance(obj, dict):
        return issues + ['JSON 객체가 아님']
    issues += _schema_issues(obj)
    kind = obj.get('kind')
    if kind not in KINDS:
        return issues + ['kind 허용값 아님'] if 'kind' not in ' '.join(issues) else issues
    # 스키마 없이도 최소 필수 검사(jsonschema 미설치 환경)
    for k in ('title', 'caption'):
        if not isinstance(obj.get(k), str) or not obj.get(k):
            issues.append(f'{k} 누락')
    src = obj.get('source') if isinstance(obj.get('source'), dict) else {}
    if src.get('data') not in DATA_SOURCES:
        issues.append('source.data 누락 또는 허용값 아님')
    txt = f"{obj.get('title', '')} {obj.get('caption', '')}"
    for w in BANNED_WORDS:
        if w in txt:
            issues.append(f'표현 제한 — "{w}"')
    uses_ref = False
    if kind == 'table':
        cols, rows = obj.get('columns') or [], obj.get('rows') or []
        for i, r in enumerate(rows):
            if not isinstance(r, list) or len(r) != len(cols):
                issues.append(f'{i + 1}행 길이가 columns 와 다름')
        pos = obj.get('positions')
        if pos is not None:
            uses_ref = True
            if not isinstance(pos, list) or len(pos) != len(rows):
                issues.append('positions 길이가 rows 와 다름')
        if any('기준' in str(c) for c in cols):
            uses_ref = True
    elif kind == 'line':
        prev = ''
        for i, p in enumerate(obj.get('series') or []):
            d = p.get('date') if isinstance(p, dict) else None
            if isinstance(d, str) and DATE_RE.match(d):
                if d <= prev:
                    issues.append('series 날짜가 오름차순이 아님')
                prev = d
        if obj.get('reference'):
            uses_ref = True
    elif kind == 'range':
        uses_ref = True
        bands = obj.get('bands') or []
        for i in range(1, len(bands)):
            a, b = bands[i - 1], bands[i]
            if isinstance(a, dict) and isinstance(b, dict) and _is_num(b.get('from')) and _is_num(a.get('to')) \
                    and b['from'] < a['to']:
                issues.append('bands 가 오름차순 연속이 아님')
    elif kind == 'timeline':
        for i, it in enumerate(obj.get('items') or []):
            if isinstance(it, dict) and isinstance(it.get('from'), str) and isinstance(it.get('to'), str) \
                    and it['to'] < it['from']:
                issues.append(f'{i + 1}번째 item 의 to 가 from 보다 앞')
    if uses_ref and not src.get('ref'):
        issues.append('기준값을 쓰는 블록은 source.ref(기준 출처) 필수')
    # 중복 제거(스키마와 자체 검사가 같은 것을 잡은 경우)
    seen, uniq = set(), []
    for s in issues:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def check_answer(text):
    """답변 하나의 형식 검사. {'blocks': n, 'ok': bool, 'issues': [...], 'per_block': [[...], ...]}"""
    closed, unclosed = iter_blocks(text or '')
    issues, per_block = [], []
    for t in OPEN_RE.findall(text or ''):
        if t != 'mhc-viz':
            issues.append(f'펜스 태그 변형 ({t}) — 정확히 mhc-viz')
    if unclosed:
        issues.append('닫히지 않은 mhc-viz 펜스')
    if len(closed) > MAX_BLOCKS:
        issues.append(f'블록 {len(closed)}개 — 답변당 최대 {MAX_BLOCKS}개')
    for i, b in enumerate(closed, 1):
        try:
            obj = json.loads(b['json'])
        except json.JSONDecodeError as e:
            per_block.append([f'JSON 파싱 실패 — {e.msg} (line {e.lineno})'])
            continue
        per_block.append(validate_block(obj, b['json']))
    bad = sum(1 for p in per_block if p)
    return {'blocks': len(closed), 'unclosed': bool(unclosed), 'ok': not issues and bad == 0,
            'issues': issues, 'per_block': per_block, 'invalid_blocks': bad}


def strip_blocks(text, mode='caption'):
    """평가기 입력용 치환. mode='caption': 블록 → "[표: caption]" 한 줄(캡션이 없거나 깨지면 "[표: (해석 불가)]").
    mode='remove': 블록을 없앤다. 닫히지 않은 블록은 펜스부터 끝까지 같은 규칙으로 처리한다."""
    if not text or '```mhc-viz' not in text:
        return text

    def repl(m):
        if mode == 'remove':
            return ''
        try:
            obj = json.loads(m.group(1))
            cap = obj.get('caption') if isinstance(obj, dict) else None
        except Exception:
            cap = None
        cap = (cap or '').strip() or '(해석 불가)'
        return f'[표: {cap}]'

    out = FENCE_RE.sub(repl, text)
    idx = out.find('```mhc-viz')
    if idx >= 0:
        out = out[:idx].rstrip() + ('' if mode == 'remove' else '\n[표: (해석 불가)]')
    return re.sub(r'\n{3,}', '\n\n', out).strip()


def render_fallback_note(report):
    """로그·리포트용 한 줄."""
    if not report['blocks'] and not report['unclosed']:
        return ''
    parts = [f"mhc-viz {report['blocks']}개"]
    if report['invalid_blocks']:
        parts.append(f"형식 위반 {report['invalid_blocks']}개")
    if report['unclosed']:
        parts.append('미닫힘 1')
    return ' · '.join(parts)
