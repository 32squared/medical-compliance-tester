# -*- coding: utf-8 -*-
"""mhc_viz — 블록 추출·검증·평가용 치환 (규약 v1.0, docs/mhc_viz_convention_v1_20261014.html)."""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import mhc_viz  # noqa: E402

TABLE = {"v": 1, "kind": "table", "title": "간 수치 4회 검진 비교 (IU/L)",
         "columns": ["항목", "2016", "2018", "2020", "2022", "기준"],
         "rows": [["ALT", 87, 45, 124, 47, "35 이하"], ["AST", 49, 27, 89, 31, "40 이하"],
                  ["감마지티피", 68, 56, 110, 67, "11~63"]],
         "positions": ["above", "in", "above"],
         "caption": "2022년 기준 ALT와 감마지티피는 참고범위보다 높고 AST는 범위 안.",
         "source": {"data": "phr.checkup", "ref": "국민건강보험공단 일반검진 참고범위"}}
LINE = {"v": 1, "kind": "line", "title": "ALT 추이 2016~2022", "unit": "IU/L",
        "series": [{"date": "2016-12-29", "value": 87}, {"date": "2018-11-20", "value": 45},
                   {"date": "2020-11-24", "value": 124}, {"date": "2022-11-21", "value": 47}],
        "reference": {"high": 35, "label": "참고범위 상한"},
        "caption": "ALT는 2020년 124로 가장 높았다가 2022년 47로 내려왔으나 상한 35보다 높다.",
        "source": {"data": "phr.checkup", "ref": "국민건강보험공단 일반검진 참고범위"}}
RANGE = {"v": 1, "kind": "range", "title": "공복혈당 90 mg/dL 의 위치", "value": 90, "unit": "mg/dL",
         "bands": [{"from": 70, "to": 99, "label": "정상"}, {"from": 100, "to": 125, "label": "공복혈당장애"},
                   {"from": 126, "to": None, "label": "당뇨병 의심"}],
         "caption": "공복혈당 90은 정상 구간 안.", "source": {"data": "phr.checkup", "ref": "공단 일반검진 판정 기준"}}
TIMELINE = {"v": 1, "kind": "timeline", "title": "최근 처방 2건",
            "items": [{"label": "알마겔정", "from": "2025-01-02", "to": "2025-01-09", "status": "ended"},
                      {"label": "록펜정", "from": "2024-12-02", "to": "2024-12-07", "status": "ended"}],
            "caption": "두 처방 모두 종료.", "source": {"data": "phr.prescription"}}


def fence(obj):
    return '```mhc-viz\n' + json.dumps(obj, ensure_ascii=False) + '\n```'


def test_fixtures_pass():
    for obj in (TABLE, LINE, RANGE, TIMELINE):
        assert mhc_viz.validate_block(obj, json.dumps(obj, ensure_ascii=False)) == [], obj['kind']


def test_answer_with_two_blocks_ok():
    text = '요약 문장.\n\n' + fence(TABLE) + '\n\n이어지는 문장.\n\n' + fence(LINE) + '\n\n끝.'
    rep = mhc_viz.check_answer(text)
    assert rep['ok'] and rep['blocks'] == 2 and not rep['unclosed']


def test_missing_caption_banned_word_and_ref():
    bad = {"v": 1, "kind": "table", "title": "비만 진단 결과", "columns": ["항목", "값"],
           "rows": [["체질량지수", 26.5]], "positions": ["above"], "source": {"data": "phr.checkup"}}
    issues = mhc_viz.validate_block(bad)
    joined = ' '.join(issues)
    assert 'caption' in joined
    assert '진단' in joined
    assert 'source.ref' in joined


def test_line_date_order_and_types():
    bad = dict(LINE, series=[{"date": "2020-11-24", "value": 124}, {"date": "2018-11-20", "value": "45"}])
    issues = ' '.join(mhc_viz.validate_block(bad))
    assert '오름차순' in issues
    assert 'value' in issues  # 스키마: 문자열 값


def test_unclosed_and_tag_variant_and_count():
    text = '```MHC-VIZ\n{}\n```\n' + fence(TABLE) * 4 + '\n```mhc-viz\n{"v":1'
    rep = mhc_viz.check_answer(text)
    joined = ' '.join(rep['issues'])
    assert '변형' in joined and '닫히지' in joined and '최대' in joined
    assert rep['unclosed']


def test_strip_blocks_caption_mode():
    text = '앞 문장.\n\n' + fence(TABLE) + '\n\n뒤 문장.'
    out = mhc_viz.strip_blocks(text)
    assert '```' not in out
    assert '[표: 2022년 기준 ALT와 감마지티피는' in out
    assert out.startswith('앞 문장.') and out.endswith('뒤 문장.')


def test_strip_blocks_unclosed_and_remove():
    text = '앞 문장.\n\n```mhc-viz\n{"v":1,"kind":"table"'
    assert mhc_viz.strip_blocks(text) == '앞 문장.\n[표: (해석 불가)]'
    assert mhc_viz.strip_blocks(text, mode='remove') == '앞 문장.'
    assert mhc_viz.strip_blocks('블록 없음') == '블록 없음'
    assert mhc_viz.strip_blocks('') == ''


def test_table_row_length_and_positions():
    bad = dict(TABLE, rows=[["ALT", 87, 45]], positions=["above", "in"])
    issues = ' '.join(mhc_viz.validate_block(bad))
    assert 'columns 와 다름' in issues and 'positions' in issues
