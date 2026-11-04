"""An expired Codex login fails over to the next vendor, never retries itself (#1009).

``retryable`` means "re-issue the call against the same login"; an expired
ChatGPT-subscription credential is deliberately *not* retryable, because no
retry of that login can succeed. But the next vendor's credential is
independent of it, so the cascade must still hand the review on. The driver
says so with ``metadata["failover_eligible"]``; these tests pin that the chain
walk honours it without ever re-running the expired rung against itself.
"""

from __future__ import annotations

import pytest

from mergecraft.agents.codex import CODEX_CREDENTIAL_EXPIRED_KIND, CODEX_CREDENTIAL_EXPIRED_REASON
from mergecraft.agents.shared import FAILOVER_ELIGIBLE_KEY, INFRA_REASON_KEY, AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.utils import agent_resolve as ar

OPENCODE = "opencode-go/deepseek-v4.1-flash"
CODEX = "openai/gpt-terra"
CLAUDE = "anthropic/claude-sonnet"


def _expired_codex() -> AgentResult:
    """The exact metadata shape the Codex driver returns for a retired login."""
    return AgentResult(
        success=False,
        error=f"{CODEX_CREDENTIAL_EXPIRED_REASON}\n\ncodex reported: refresh token was already used",
        metadata={
            INFRA_REASON_KEY: CODEX_CREDENTIAL_EXPIRED_KIND,
            "retryable": False,
            FAILOVER_ELIGIBLE_KEY: True,
        },
    )


_HARNESS = {OPENCODE: "opencode", CODEX: "codex", CLAUDE: "claude"}


@pytest.fixture(autouse=True)
def _hermetic_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    # The cascade's three vendors, without a provider registry on disk: the
    # OpenCode Go rung is served by the opencode harness, as in the workflow.
    monkeypatch.setattr(ar, "_agent_binary_available", lambda _slug: True)
    monkeypatch.setattr(ar, "_chain_deadline", lambda: None)
    monkeypatch.setattr(ar, "_agent_mode_for_slug", lambda slug, settings=None: _HARNESS[slug])
    monkeypatch.setattr(ar, "resolve_harness", lambda _settings, slug: _HARNESS[slug])
    monkeypatch.setattr(
        "mergecraft.enterprise.runtime.enforce_routed_model_residency", lambda _slug: None
    )


def test_failover_eligible_is_distinct_from_retryable() -> None:
    result = _expired_codex()

    assert ar._is_retryable_failure(result) is False
    assert ar._is_failover_eligible(result) is True
    assert ar._may_advance_chain(result) is True


@pytest.mark.parametrize("flag", [None, False, "true", 1])
def test_only_the_literal_true_flag_is_failover_eligible(flag: object) -> None:
    metadata: dict[str, object] = {"retryable": False}
    if flag is not None:
        metadata[FAILOVER_ELIGIBLE_KEY] = flag
    result = AgentResult(success=False, error="401", metadata=metadata)

    assert ar._is_failover_eligible(result) is False
    assert ar._may_advance_chain(result) is False


async def test_opencode_without_verdict_then_expired_codex_selects_the_claude_backstop() -> None:
    settings = RepoSettings.model_validate({"models": [OPENCODE, CODEX, CLAUDE]})
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        if slug == OPENCODE:
            # Fails retryably and never reaches a verdict.
            return AgentResult(success=False, error="upstream 503", metadata={"retryable": True})
        if slug == CODEX:
            return _expired_codex()
        return AgentResult(success=True, output="reviewed", terminal_submission_received=True)

    slug, result = await ar.run_with_model_chain(settings=settings, run_once=run_once)

    assert slug == CLAUDE
    assert result.success is True
    # The expired Codex rung ran exactly once: failover, never a same-login retry.
    assert attempts.count(CODEX) == 1
    assert attempts[-1] == CLAUDE


async def test_expired_codex_at_the_chain_tail_is_not_rerun_against_itself() -> None:
    settings = RepoSettings.model_validate({"models": [CODEX]})
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return _expired_codex()

    slug, result = await ar.run_with_model_chain(settings=settings, run_once=run_once, pin=True)

    assert attempts == [CODEX]
    assert slug == CODEX
    assert result.success is False
    assert result.metadata[FAILOVER_ELIGIBLE_KEY] is True
    assert result.metadata[INFRA_REASON_KEY] == CODEX_CREDENTIAL_EXPIRED_KIND


async def test_a_retryable_failure_at_the_tail_still_gets_its_one_retry() -> None:
    """Control: the tail-retry allowance is unchanged for genuinely retryable failures."""
    settings = RepoSettings.model_validate({"models": [CODEX]})
    attempts: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        attempts.append(slug)
        return AgentResult(success=False, error="upstream 503", metadata={"retryable": True})

    await ar.run_with_model_chain(settings=settings, run_once=run_once, pin=True)

    assert attempts == [CODEX, CODEX]


async def test_allow_fallback_false_still_refuses_to_fail_over() -> None:
    settings = RepoSettings.model_validate({"models": [CODEX, CLAUDE], "allow_fallback": False})

    async def run_once(slug: str) -> AgentResult:
        return _expired_codex()

    with pytest.raises(ar.ModelFallbackPolicyError):
        await ar.run_with_model_chain(settings=settings, run_once=run_once)
