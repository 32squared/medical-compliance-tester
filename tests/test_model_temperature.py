# -*- coding: utf-8 -*-
"""모델별 temperature 전송 규칙 — gpt-5·gpt-6·o 계열은 temperature 를 거부한다(400 Unsupported value).

2026-10-14 gpt-6-luna·gpt-6.1-sol 실측으로 확인. 호스트(proxy_server) 경로를 본다. OpenAI 키·네트워크 불필요.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def _import_proxy():
    """proxy_server 는 import 시점에 sys.stdout/err 을 UTF-8 래퍼로 바꾼다 — pytest 캡처 객체를 되돌린다."""
    out, err = sys.stdout, sys.stderr
    try:
        import proxy_server
    finally:
        for stream, orig in ((sys.stdout, out), (sys.stderr, err)):
            if stream is not orig:
                try:
                    stream.detach()
                except Exception:
                    pass
        sys.stdout, sys.stderr = out, err
    return proxy_server


proxy_server = _import_proxy()


@pytest.mark.parametrize("model", ["gpt-4o-mini", "gpt-4.1", "GPT-4o", "gpt-3.5-turbo"])
def test_gpt4_family_sends_temperature(model):
    assert proxy_server._model_accepts_temperature(model) is True


@pytest.mark.parametrize("model", [
    "gpt-5.4", "gpt-5.4-mini", "gpt-5.6-luna",
    "gpt-6-luna", "gpt-6-sol", "gpt-6.1-sol", "GPT-6-Astra",
    "o1", "o3", "o4-mini", "", None,
])
def test_gpt5_gpt6_o_family_omits_temperature(model):
    assert proxy_server._model_accepts_temperature(model) is False



# 판정기(medical_eval.judge_client.uses_temperature) 쪽 규칙은 판정기 저장소의 tests/test_judge_client.py 가 검증한다
# (main 95edec8, REQ-2VJY). 호스트 테스트는 판정기를 직접 import 하지 않는다(scripts/check_no_cross_import.py --forbid eval).


@pytest.mark.parametrize("model,env,expected", [
    ("gpt-6-luna", None, "low"),          # 기본값 low
    ("gpt-6-sol", "low", "low"),
    ("gpt-6-luna", "none", "none"),
    ("gpt-6.1-sol", "medium", "medium"),
    ("gpt-6-luna", "", None),             # 빈 값 → 보내지 않음(모델 기본 추론)
    ("gpt-6-luna", "off", None),
    ("gpt-5.4-mini", "low", None),        # gpt-6 계열이 아니면 보내지 않음
    ("gpt-4o-mini", "low", None),
])
def test_reasoning_effort_only_for_gpt6(monkeypatch, model, env, expected):
    if env is None:
        monkeypatch.delenv("OPENAI_REASONING_EFFORT", raising=False)
    else:
        monkeypatch.setenv("OPENAI_REASONING_EFFORT", env)
    assert proxy_server._reasoning_effort_for(model) == expected


def test_apply_model_params_combines_rules(monkeypatch):
    monkeypatch.setenv("OPENAI_REASONING_EFFORT", "low")
    assert proxy_server._apply_model_params({}, "gpt-4o-mini", 0.1) == {"temperature": 0.1}
    assert proxy_server._apply_model_params({}, "gpt-5.4", 0.1) == {}
    assert proxy_server._apply_model_params({}, "gpt-6-sol", 0.1) == {"reasoning_effort": "low"}
    body = {"model": "gpt-6-luna", "messages": []}
    proxy_server._apply_model_params(body, "gpt-6-luna", 0.0)
    assert body == {"model": "gpt-6-luna", "messages": [], "reasoning_effort": "low"}
