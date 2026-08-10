"""Unit tests for Nous / TokenHub gateway credential resolution."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.openai_compatible_gateways import (
    resolve_gateway_endpoint,
)
from mergecraft.utils.agent_resolve import (
    has_credentials_for_slug,
    resolve_runtime_agent,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


@pytest.fixture(autouse=True)
def _clear_gateway_env(monkeypatch: MonkeyPatch) -> None:
    for key in (
        "NOUS_API_KEY",
        "NOUS_BASE_URL",
        "TOKENHUB_API_KEY",
        "TOKENHUB_BASE_URL",
        "MERGECRAFT_CUSTOM_PROVIDER_BASE_URL",
        "MERGECRAFT_CUSTOM_PROVIDER_API_KEY",
        "MERGECRAFT_AGENT",
        "OPENAI_API_KEY",
        "CODEX_AUTH_JSON",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_has_credentials_for_nous_and_tokenhub(monkeypatch: MonkeyPatch) -> None:
    assert not has_credentials_for_slug("nous/deepseek/deepseek-v4-flash")
    assert not has_credentials_for_slug("tokenhub/hy3")

    monkeypatch.setenv("NOUS_API_KEY", "n-key")
    assert has_credentials_for_slug("nous/deepseek/deepseek-v4-flash")

    monkeypatch.delenv("NOUS_API_KEY")
    monkeypatch.setenv("TOKENHUB_API_KEY", "t-key")
    assert has_credentials_for_slug("tokenhub/hy3")
    assert has_credentials_for_slug("tokenhub/deepseek-v4-flash")


def test_resolve_runtime_agent_routes_gateways_to_opencode(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOKENHUB_API_KEY", "t-key")
    agent = resolve_runtime_agent(model="tokenhub/hy3")
    assert agent.name == "opencode"

    monkeypatch.delenv("TOKENHUB_API_KEY")
    monkeypatch.setenv("NOUS_API_KEY", "n-key")
    agent = resolve_runtime_agent(model="nous/deepseek/deepseek-v4-flash")
    assert agent.name == "opencode"


def test_resolve_gateway_endpoint_tokenhub_default_url(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("TOKENHUB_API_KEY", "t-key")
    endpoint = resolve_gateway_endpoint("tokenhub/hy3")
    assert endpoint == (
        "tokenhub",
        "https://tokenhub-intl.tencentcloudmaas.com/v1",
        "t-key",
    )
