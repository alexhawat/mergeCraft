"""RH3 — chain fallback uses mergeCraft classifiers."""

from __future__ import annotations

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.utils.agent_resolve import _is_retryable_failure, run_with_model_chain


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


def test_parse_failure_is_not_retryable() -> None:
    result = AgentResult(success=False, error="parse failure")
    assert _is_retryable_failure(result) is False


@pytest.mark.asyncio
async def test_opencode_retries_at_most_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """OpenCode gets the initial attempt plus exactly one retry, then the chain
    stops spending wall clock on that harness (#444).
    """
    monkeypatch.setenv("NOUS_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    settings = RepoSettings.model_validate(
        {
            "models": [
                "nous/deepseek/deepseek-v4-flash",
                "nous/deepseek/deepseek-v4-pro",
                "nous/qwen/qwen3.8-max",
            ]
        }
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(
            success=False,
            error="opencode provider request timed out: ",
            metadata={"retryable": True},
        )

    slug, result = await run_with_model_chain(settings=settings, run_once=run_once)
    assert len(attempts) == 2, f"opencode ran {len(attempts)} times, expected 2: {attempts}"
    assert result.success is False
    assert slug


@pytest.mark.asyncio
async def test_chain_stops_advancing_once_the_run_budget_is_spent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exhausted run budget stops the chain instead of letting retryable
    timeouts multiply into a multi-hour run (#444).
    """
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    # Deadline already in the past: the first attempt still runs, the advance
    # to the second entry must not.
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._chain_deadline",
        lambda: __import__("time").monotonic() - 1.0,
    )
    settings = RepoSettings.model_validate(
        {"models": ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]}
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(success=False, error="boom", metadata={"retryable": True})

    _slug, result = await run_with_model_chain(settings=settings, run_once=run_once)
    assert attempts == ["openai/gpt-5.3-codex"]
    assert result.success is False
