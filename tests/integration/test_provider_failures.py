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
    # The evidence must name the slug that actually ran. The tail entry is only
    # *skipped* once the allowance is spent, so stamping it would blame a model
    # that never executed.
    meta = result.metadata or {}
    assert meta["executed_model"] == attempts[-1]
    assert slug == attempts[-1]
    assert attempts[-1] != settings.models[-1]


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


class TestRetryabilityHasOneDecisionPath:
    """#447 — the deciding classifier must not ignore the failure itself.

    ``_is_retryable_failure`` gated on ``metadata['retryable']`` alone while
    ``_retryable_failure_reason`` inferred the same property from the error
    text, and only the metadata-blind one decided. A driver that omitted the
    flag therefore read as "permanent", which is how #444 cost a whole review.
    """

    def test_an_explicit_true_is_believed(self) -> None:
        result = AgentResult(success=False, error="anything", metadata={"retryable": True})
        assert _is_retryable_failure(result) is True

    def test_an_explicit_false_overrides_retryable_looking_text(self) -> None:
        """A driver that says "permanent" is believed even when the text says
        otherwise — inference must never overrule a stated intent.
        """
        result = AgentResult(
            success=False,
            error="request timed out",
            metadata={"retryable": False},
        )
        assert _is_retryable_failure(result) is False

    @pytest.mark.parametrize(
        "error",
        [
            "opencode provider request timed out: ",
            "codex CLI timed out",
            "provider crash during turn",
            "You've hit your usage limit.",
            "429 rate limit exceeded",
        ],
        ids=["opencode-timeout", "cli-timeout", "crash", "quota", "rate-limit"],
    )
    def test_an_omitted_flag_falls_back_to_inference(self, error: str) -> None:
        """The #444 shape: no metadata, but the error plainly says "recoverable"."""
        assert _is_retryable_failure(AgentResult(success=False, error=error)) is True

    def test_an_omitted_flag_on_an_ordinary_failure_stays_permanent(self) -> None:
        """Inference must not turn every failure into a retry."""
        result = AgentResult(success=False, error="SyntaxError: invalid syntax")
        assert _is_retryable_failure(result) is False


@pytest.mark.asyncio
async def test_a_driver_that_forgets_the_flag_does_not_kill_the_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end #447: an omitted flag degrades to inference, not to a dead run."""
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
            # No metadata at all — the omission this issue is about.
            return AgentResult(success=False, error="provider request timed out")
        return AgentResult(success=True, output="ok")

    slug, result = await run_with_model_chain(settings=settings, run_once=run_once)
    assert attempts == ["openai/gpt-5.3-codex", "google/gemini-3.1-pro-preview"]
    assert slug == "google/gemini-3.1-pro-preview"
    assert result.success is True


@pytest.mark.asyncio
async def test_a_tail_failure_returns_rather_than_exhausting_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A retryable failure with no fallback left gets one retry, then answers.

    Widening retryability (#447) made this branch easy to reach. Unbounded, a
    single-entry chain re-asked the same refusing provider until the attempt
    cap tripped and then raised ``RuntimeError`` — spending the budget and
    replacing the real error with a cap message.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(
        "mergecraft.utils.agent_resolve._agent_binary_available", lambda _slug: True
    )
    settings = RepoSettings.model_validate({"models": ["openai/gpt-5.3-codex"]})
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(success=False, error="api quota exhausted")

    # pin=True collapses the chain to its head; without it the configured
    # fallback tail is appended and this exercises advance, not tail retry.
    _slug, result = await run_with_model_chain(settings=settings, run_once=run_once, pin=True)
    assert len(attempts) == 2, f"expected one retry, got {len(attempts)}"
    assert result.success is False
    assert result.error == "api quota exhausted"
