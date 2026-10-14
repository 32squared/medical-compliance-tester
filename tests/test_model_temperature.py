# -*- coding: utf-8 -*-
"""모델별 temperature 전송 규칙 — gpt-5·gpt-6·o 계열은 temperature 를 거부한다(400 Unsupported value).

2026-10-14 gpt-6-luna·gpt-6.1-sol 실측으로 확인. 호스트(proxy_server)와 판정기 어댑터(eval_v3)의
두 경로가 같은 규칙을 따르는지 본다. OpenAI 키·네트워크 불필요.
"""
import os
import sys
import types

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import eval_v3  # noqa: E402


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


def _fake_medical_eval(uses_temperature):
    me = types.ModuleType("medical_eval_fake")
    jc = types.ModuleType("judge_client_fake")
    jc.uses_temperature = uses_temperature
    me.judge_client = jc
    return me


def test_patch_adds_gpt6_when_judge_lacks_it():
    """판정기가 gpt-5·o 계열만 제외하면(현재 medical_eval) gpt-6 도 제외하도록 덮어쓴다."""
    def legacy(model):
        return not (model or "").lower().startswith(("gpt-5", "o1", "o3", "o4"))

    me = _fake_medical_eval(legacy)
    eval_v3._patch_uses_temperature(me)
    f = me.judge_client.uses_temperature
    assert f("gpt-6-luna") is False
    assert f("gpt-6.1-sol") is False
    assert f("gpt-5.4-mini") is False
    assert f("gpt-4o-mini") is True
    assert getattr(f, "_gpt6_patched", False) is True
    # 두 번 호출해도 한 번만 감싼다
    eval_v3._patch_uses_temperature(me)
    assert me.judge_client.uses_temperature is f


def test_patch_is_noop_when_judge_already_handles_gpt6():
    """판정기 저장소가 REQ-2VJY 를 반영해 gpt-6 을 제외하면 손대지 않는다."""
    def fixed(model):
        return (model or "").lower().startswith(("gpt-4", "gpt-3.5"))

    me = _fake_medical_eval(fixed)
    eval_v3._patch_uses_temperature(me)
    assert me.judge_client.uses_temperature is fixed


def test_patch_tolerates_missing_judge_client():
    me = types.ModuleType("medical_eval_fake")
    eval_v3._patch_uses_temperature(me)  # 예외 없이 끝난다
