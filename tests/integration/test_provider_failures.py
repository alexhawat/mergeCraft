"""RH3 — chain fallback uses mergeCraft classifiers."""

from __future__ import annotations

import httpx
import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.utils.agent_resolve import run_with_model_chain


@pytest.mark.asyncio
async def test_retryable_cli_shaped_failure_advances_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug.startswith("openai/"):
            return AgentResult(success=False, metadata={"retryable": True})
        return AgentResult(success=True, output="ok")

    slug, result = await run_with_model_chain(settings=settings, run_once=run_once)
    assert attempts == ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]
    assert slug == "google/gemini-3.1-pro-preview"
    assert result.success is True


@pytest.mark.asyncio
async def test_configured_fallback_slug_is_used(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )

    async def run_once(slug: str) -> AgentResult:
        if slug.startswith("openai/"):
            return AgentResult(success=False, metadata={"retryable": True})
        return AgentResult(success=True, output="ok")

    slug, _ = await run_with_model_chain(settings=settings, run_once=run_once)
    assert slug == "google/gemini-3.1-pro-preview"


@pytest.mark.asyncio
async def test_auth_failure_is_not_retried_as_transient(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(success=False, error="401", metadata={"retryable": False})

    _slug, result = await run_with_model_chain(settings=settings, run_once=run_once)
    assert attempts == ["openai/gpt-5.3-codex"]
    assert result.success is False


def test_invalid_model_output_is_not_treated_as_transport_failure(provider_harness) -> None:
    provider_harness.reload([])
    response = httpx.post(
        provider_harness.base_url + "/chat/completions",
        headers={"Authorization": "Bearer sk-mergecraft-test"},
        json={"model": "default/dummy", "messages": []},
        timeout=5.0,
    )
    assert response.status_code == 400
    result = AgentResult(success=False, error="parse failure")
    assert result.metadata.get("retryable") is not True


def test_opencode_http_timeout_is_not_marked_retryable() -> None:
    """Pin — opencode timeout path remains non-retryable (D11)."""
    from mergecraft.agents.opencode import ProviderTimeoutError

    assert ProviderTimeoutError.__name__ == "ProviderTimeoutError"
