"""RED tests for ordered model chain resolution at runtime (issue #14 / W19)."""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, cast

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.models import _MAX_FALLBACK_DEPTH

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
    "MERGECRAFT_MODEL",
)


def _clear_provider_env(monkeypatch: MonkeyPatch) -> None:
    for key in _PROVIDER_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def _import_chain_symbol(name: str) -> object:
    module = importlib.import_module("mergecraft.utils.agent_resolve")
    try:
        return getattr(module, name)
    except AttributeError as exc:
        pytest.fail(f"mergecraft.utils.agent_resolve.{name} not implemented: {exc}")


def _chain_settings(slugs: list[str]) -> RepoSettings:
    return RepoSettings.model_validate({"models": slugs})


@pytest.mark.xfail(
    reason="green after W19: chain skips entries without required credentials (#14)",
    strict=False,
)
def test_model_chain_skips_slugs_without_credentials(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    select_runnable_model_slug = cast(
        "Callable[..., str]",
        _import_chain_symbol("select_runnable_model_slug"),
    )
    settings = _chain_settings(
        [
            "anthropic/claude-sonnet",
            "openai/gpt-5.3-codex",
            "google/gemini-3.1-pro-preview",
        ]
    )

    selected = select_runnable_model_slug(settings=settings)

    assert selected == "google/gemini-3.1-pro-preview"


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W19: chain advances on retryable provider failure (#14)",
    strict=False,
)
async def test_model_chain_advances_on_retryable_provider_failure(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("CODEX_AUTH_JSON", '{"access_token":"test-token"}')
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    run_with_model_chain = cast(
        "Callable[..., Awaitable[tuple[str, AgentResult]]]",
        _import_chain_symbol("run_with_model_chain"),
    )
    settings = _chain_settings(
        [
            "openai/gpt-5.3-codex",
            "google/gemini-3.1-pro-preview",
        ]
    )
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug == "openai/gpt-5.3-codex":
            return AgentResult(
                success=False,
                error="provider rate limited",
                metadata={"retryable": True},
            )
        return AgentResult(success=True, output="review complete")

    selected_slug, result = await run_with_model_chain(
        settings=settings,
        run_once=run_once,
    )

    assert attempts == ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]
    assert selected_slug == "google/gemini-3.1-pro-preview"
    assert result.success is True


@pytest.mark.asyncio
@pytest.mark.xfail(
    reason="green after W19: chain caps total attempts at max depth (#14)",
    strict=False,
)
async def test_model_chain_caps_attempts_at_max_depth(
    monkeypatch: MonkeyPatch,
) -> None:
    _clear_provider_env(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")

    run_with_model_chain = cast(
        "Callable[..., Awaitable[tuple[str, AgentResult]]]",
        _import_chain_symbol("run_with_model_chain"),
    )
    settings = _chain_settings(["openai/gpt-5.3-codex"])
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(
            success=False,
            error="transient provider failure",
            metadata={"retryable": True},
        )

    with pytest.raises(RuntimeError, match=r"max|cap|attempt"):
        await run_with_model_chain(
            settings=settings,
            run_once=run_once,
            max_attempts=_MAX_FALLBACK_DEPTH,
        )

    assert len(attempts) == _MAX_FALLBACK_DEPTH
