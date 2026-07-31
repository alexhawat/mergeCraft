"""D12 fail-loud tests for ``resolve_runtime_agent`` (Batch D / W11, issues #10-#13)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents import agents
from mergecraft.utils.agent_resolve import resolve_runtime_agent

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

_PROVIDER_ENV_KEYS = (
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "CODEX_AUTH_JSON",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_GENERATIVE_AI_API_KEY",
    "CURSOR_API_KEY",
    "MERGECRAFT_AGENT",
)


def _clear_provider_env(monkeypatch: MonkeyPatch) -> None:
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


_FAIL_LOUD_CASES = (
    pytest.param(
        "openai/gpt-5.3-codex",
        ("CODEX_AUTH_JSON", "OPENAI_API_KEY"),
        id="codex-subscription-slug",
    ),
    pytest.param(
        "openai/gpt-5.6-sol",
        ("OPENAI_API_KEY", "CODEX_AUTH_JSON"),
        id="openai-api-slug",
    ),
    pytest.param(
        "google/gemini-3.1-pro-preview",
        ("GEMINI_API_KEY", "GOOGLE_GENERATIVE_AI_API_KEY"),
        id="google-gemini-slug",
    ),
    pytest.param(
        "cursor/cloud-agent",
        ("CURSOR_API_KEY",),
        id="cursor-cloud-slug",
    ),
)


@pytest.mark.parametrize(("model", "credential_env_hints"), _FAIL_LOUD_CASES)
def test_resolve_runtime_agent_fail_loud_without_credentials(
    model: str,
    credential_env_hints: tuple[str, ...],
    monkeypatch: MonkeyPatch,
) -> None:
    """Non-Anthropic models must not silently fall through to ``opencode`` without creds."""
    _clear_provider_env(monkeypatch)

    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        resolve_runtime_agent(model=model)

    message = str(exc_info.value)
    lowered = message.lower()
    assert "opencode" not in lowered
    assert any(env.lower() in lowered for env in credential_env_hints), (
        f"expected one of {credential_env_hints} in error message, got: {message!r}"
    )


@pytest.mark.parametrize(
    "model",
    [
        pytest.param(
            "openai/gpt-5.3-codex",
            id="codex-subscription-slug",
        ),
        pytest.param(
            "openai/gpt-5.6-sol",
            id="openai-api-slug",
        ),
        pytest.param(
            "google/gemini-3.1-pro-preview",
            id="google-gemini-slug",
        ),
        pytest.param(
            "cursor/cloud-agent",
            id="cursor-cloud-slug",
        ),
    ],
)
def test_resolve_runtime_agent_never_returns_opencode_for_provider_models(
    model: str,
    monkeypatch: MonkeyPatch,
) -> None:
    """Document the anti-pattern: missing creds must not resolve to the ``opencode`` agent."""
    _clear_provider_env(monkeypatch)

    try:
        agent = resolve_runtime_agent(model=model)
    except ValueError, RuntimeError:
        return

    assert agent.name != "opencode", (
        f"resolve_runtime_agent({model!r}) silently fell through to opencode"
    )


def test_resolve_runtime_agent_selects_codex_with_codex_auth_json(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')

    agent = resolve_runtime_agent(model="openai/gpt-5.3-codex")

    assert agent.name == "codex"
    assert "codex" in agents


def test_resolve_runtime_agent_selects_codex_with_openai_api_key_only(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    agent = resolve_runtime_agent(model="openai/gpt-5.6-sol")

    assert agent.name == "codex"


def test_resolve_runtime_agent_selects_gemini_with_gemini_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    agent = resolve_runtime_agent(model="google/gemini-3.1-pro-preview")

    assert agent.name == "gemini"
    assert "gemini" in agents


def test_resolve_runtime_agent_selects_cursor_with_cursor_api_key(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("CURSOR_API_KEY", "cursor-test-key")

    agent = resolve_runtime_agent(model="cursor/cloud-agent")

    assert agent.name == "cursor"
    assert "cursor" in agents
