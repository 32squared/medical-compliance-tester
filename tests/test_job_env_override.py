# -*- coding: utf-8 -*-
"""Job 의 백엔드 환경 덮어쓰기(SKIX_ENV)와 Dev 프롬프트 버전 스탬프."""
import os

import pytest

import batch_executor as be
import eval_v3

SETTINGS = {"currentEnv": "prod", "environments": {"prod": {"xApiKey": "p"}, "dev": {"xApiKey": "d"}}}


def test_default_follows_setting(monkeypatch):
    monkeypatch.delenv("SKIX_ENV", raising=False)
    c = be.build_skix_config(SETTINGS)
    assert c["current_env"] == "prod" and c["api_url"] == "https://skix.phnyx.ai" and c["api_key"] == "p"


def test_skix_env_overrides_only_this_run(monkeypatch):
    monkeypatch.setenv("SKIX_ENV", "dev")
    c = be.build_skix_config(SETTINGS)
    assert c["current_env"] == "dev" and c["api_url"] == "https://dev-skix.phnyx.ai" and c["api_key"] == "d"
    assert SETTINGS["currentEnv"] == "prod"                       # 설정 자체는 그대로


def test_skix_env_unknown_value_ignored(monkeypatch):
    monkeypatch.setenv("SKIX_ENV", "qa")
    assert be.build_skix_config(SETTINGS)["current_env"] == "prod"


@pytest.mark.parametrize("answer,want", [
    ("(v17)\n최근 공복혈당은 …", "v17"),
    ("(v18)", "v18"),
    ("  (PHR LONGEVITY-08)\n결론: …", "PHR LONGEVITY-08"),
    ("(PHR-LONGEVITY-08) 결론", "PHR-LONGEVITY-08"),
    ("(참고) 수치는 …", None),                 # 숫자 없는 머리말
    ("(2024년 기준) …", None),                  # 글자로 시작하지 않음
    ("결론입니다 (v18)", None),                 # 첫 줄 맨 앞이 아님
    ("", None), (None, None),
])
def test_prompt_version_stamp(answer, want):
    assert eval_v3.prompt_version_of(answer) == want
