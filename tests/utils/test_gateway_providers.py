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
from tests.cli.support_provider_registry import (
    bootstrap_nous_registry,
    bootstrap_opencode_gateway,
    clear_legacy_gateway_env,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.monkeypatch import MonkeyPatch

TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"
NOUS_DEEPSEEK_MODEL = "deepseek/deepseek-v4-flash"


@pytest.fixture(autouse=True)
def _clear_gateway_env(monkeypatch: MonkeyPatch) -> None:
    clear_legacy_gateway_env(monkeypatch)
    for key in (
        "MERGECRAFT_AGENT",
        "OPENAI_API_KEY",
        "CODEX_AUTH_JSON",
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "LLM_PROVIDER_1",
        "LLM_PROVIDER_1_API_KEY",
        "LLM_PROVIDER_2",
        "LLM_PROVIDER_2_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)


def test_has_credentials_for_nous_and_tokenhub(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    assert not has_credentials_for_slug("nous/deepseek/deepseek-v4-flash")
    assert not has_credentials_for_slug("tokenhub/hy3")

    bootstrap_nous_registry(
        tmp_path,
        monkeypatch,
        model_id=NOUS_DEEPSEEK_MODEL,
        api_key="n-key",
    )
    assert has_credentials_for_slug(f"nous/{NOUS_DEEPSEEK_MODEL}")

    clear_legacy_gateway_env(monkeypatch)
    monkeypatch.delenv("LLM_PROVIDER_1_API_KEY", raising=False)
    bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="tokenhub",
        url=TOKENHUB_BASE_URL,
        model_id="hy3",
        api_key="t-key",
        env_index=2,
    )
    assert has_credentials_for_slug("tokenhub/hy3")
    assert has_credentials_for_slug("tokenhub/deepseek-v4-flash")


def test_resolve_runtime_agent_routes_gateways_to_opencode(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    tokenhub_slug = bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="tokenhub",
        url=TOKENHUB_BASE_URL,
        model_id="hy3",
        api_key="t-key",
        env_index=2,
    )
    agent = resolve_runtime_agent(model=tokenhub_slug)
    assert agent.name == "opencode"

    nous_slug = bootstrap_nous_registry(
        tmp_path,
        monkeypatch,
        model_id=NOUS_DEEPSEEK_MODEL,
        api_key="n-key",
    )
    agent = resolve_runtime_agent(model=nous_slug)
    assert agent.name == "opencode"


def test_resolve_gateway_endpoint_tokenhub_default_url(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    bootstrap_opencode_gateway(
        tmp_path,
        monkeypatch,
        label="tokenhub",
        url=TOKENHUB_BASE_URL,
        model_id="hy3",
        api_key="t-key",
        env_index=2,
    )
    endpoint = resolve_gateway_endpoint("tokenhub/hy3")
    assert endpoint == (
        "tokenhub",
        TOKENHUB_BASE_URL,
        "t-key",
    )
