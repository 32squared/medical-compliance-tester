# -*- coding: utf-8 -*-
"""배치 평가 스위치(EVAL_PHR · EVAL_V2_LEGAL · EVAL_FINAL) — LLM 없이 구성 로직만 검사한다."""
import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from batch_executor import BatchExecutor  # noqa: E402


def _make(monkeypatch, env, v3=True):
    for k in ('EVAL_PHR', 'EVAL_V2_LEGAL', 'EVAL_FINAL'):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    logs = []
    ex = BatchExecutor(
        settings={}, openai_key='k', skix_config={},
        evaluate_gpt_fn=lambda *a: {'grade': 'A'},
        evaluate_phr_fn=lambda *a: {},
        evaluate_v3_fn=(lambda *a, **kw: {}) if v3 else None,
        log_fn=logs.append,
    )
    return ex, logs


def test_default_keeps_v2_paths(monkeypatch):
    ex, logs = _make(monkeypatch, {})
    assert ex.evaluate_gpt is not None and ex.evaluate_phr is not None
    assert ex.final_mode == 'v2'
    assert logs == []                      # 기본값이면 스위치 로그 없음


def test_flags_disable_phr_and_v2_legal(monkeypatch):
    ex, logs = _make(monkeypatch, {'EVAL_PHR': '0', 'EVAL_V2_LEGAL': '0', 'EVAL_FINAL': 'v3'})
    assert ex.evaluate_phr is None and ex.evaluate_gpt is None
    assert ex.final_mode == 'v3'
    assert logs and 'EVAL_FINAL=v3' in logs[0]


@pytest.mark.parametrize('v3,expected', [
    (None, None),
    ({'error': 'boom'}, None),
    ({'legal_verdict': None}, None),
    ({'legal_verdict': 'fail', 'validity_grade': 'A'}, (0, False, 'FAIL')),
    ({'legal_verdict': 'pass', 'validity_grade': 'A'}, (100, True, 'A')),
    ({'legal_verdict': 'pass', 'validity_grade': 'D'}, (60, True, 'D')),
    ({'legal_verdict': 'pass'}, (90, True, 'PASS')),
])
def test_v3_final_mapping(monkeypatch, v3, expected):
    ex, _ = _make(monkeypatch, {'EVAL_FINAL': 'v3'})
    assert ex._v3_final(v3) == expected
