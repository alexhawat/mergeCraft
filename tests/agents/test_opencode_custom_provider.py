"""Custom OpenAI-compatible provider wiring for the opencode harness."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from tests.agents.conftest import make_agent_run_context

from mergecraft.agents.opencode import (
    CUSTOM_PROVIDER_API_KEY_ENV,
    CUSTOM_PROVIDER_BASE_URL_ENV,
    build_security_config,
)

if TYPE_CHECKING:
    from pathlib import Path

NOUS_BASE_URL = "https://inference-api.nousresearch.com/v1"
NOUS_MODEL = "nous/deepseek/deepseek-v4-flash"


@pytest.fixture(autouse=True)
def _clear_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CUSTOM_PROVIDER_BASE_URL_ENV, raising=False)
    monkeypatch.delenv(CUSTOM_PROVIDER_API_KEY_ENV, raising=False)


def _config(tmp_path: Path, model: str | None) -> dict[str, object]:
    ctx = make_agent_run_context(tmp_path, resolved_model=model)
    return json.loads(build_security_config(ctx, model))


def test_custom_provider_is_registered_from_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, NOUS_BASE_URL)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "nous-key")

    config = _config(tmp_path, NOUS_MODEL)

    assert config["provider"] == {
        "nous": {
            "npm": "@ai-sdk/openai-compatible",
            "name": "nous",
            "options": {"baseURL": NOUS_BASE_URL, "apiKey": "nous-key"},
            "models": {"deepseek/deepseek-v4-flash": {"name": "deepseek/deepseek-v4-flash"}},
        }
    }
    assert config["enabled_providers"] == ["nous"]
    assert config["model"] == NOUS_MODEL


@pytest.mark.parametrize(
    ("base_url", "api_key"),
    [(NOUS_BASE_URL, ""), ("", "nous-key"), ("", "")],
)
def test_provider_omitted_unless_both_env_vars_are_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, base_url: str, api_key: str
) -> None:
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, base_url)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, api_key)

    assert "provider" not in _config(tmp_path, NOUS_MODEL)


def test_provider_omitted_for_an_unprefixed_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(CUSTOM_PROVIDER_BASE_URL_ENV, NOUS_BASE_URL)
    monkeypatch.setenv(CUSTOM_PROVIDER_API_KEY_ENV, "nous-key")

    assert "provider" not in _config(tmp_path, "deepseek-v4-flash")


def test_unconfigured_environment_leaves_config_unchanged(tmp_path: Path) -> None:
    config = _config(tmp_path, NOUS_MODEL)

    assert "provider" not in config
    assert config["enabled_providers"] == ["nous"]
