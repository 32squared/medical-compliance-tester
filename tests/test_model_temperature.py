# -*- coding: utf-8 -*-
"""모델별 temperature 전송 규칙 — gpt-5·gpt-6·o 계열은 temperature 를 거부한다(400 Unsupported value).

2026-10-14 gpt-6-luna·gpt-6.1-sol 실측으로 확인. 호스트(proxy_server)와 판정기 어댑터(eval_v3)의
두 경로가 같은 규칙을 따르는지 본다. OpenAI 키·네트워크 불필요.
"""
import os
import sys

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



@pytest.mark.parametrize("model", ["gpt-6-luna", "gpt-6.1-sol", "gpt-6-sol", "gpt-5.4-mini", "o4-mini"])
def test_judge_client_omits_temperature_for_gpt5_gpt6(model):
    """판정기(medical_eval 95edec8+, REQ-2VJY)도 같은 규칙을 따른다 — 서브모듈이 없으면 건너뛴다."""
    if not eval_v3.available()[0]:
        pytest.skip("packages/medical_eval 서브모듈 미초기화")
    eval_v3._import_medical_eval()
    from medical_eval import judge_client
    assert judge_client.uses_temperature(model) is False
    assert judge_client.uses_temperature("gpt-4o-mini") is True
