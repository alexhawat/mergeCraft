"""HA2 — semantic fallback: the model chain advances on missing terminal verdict (D13).

Wave plan: `.ignorelocal/01-review-integrity-wave-plan.md` PR HA2.
Worktree: `mergecraft-ha2-semantic-fallback` @ `wave/ha2-semantic-fallback`

Locked **D13**: fallback triggers on ``not terminal_submission_received``, not on
verdict content. A valid ``request_changes`` is a usable result and must not
advance the chain. ``fallback_reason`` keeps "review failed" distinct from
"review says PR fails".

Every case drives the real ``run_with_model_chain`` with a scripted ``run_once``.
The walk loop is not reimplemented here — deleting the D13 guard in
``src/mergecraft/utils/agent_resolve.py`` must fail this suite.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.shared import AgentResult, AgentUsage
from mergecraft.config.settings import RepoSettings
from mergecraft.utils.agent_resolve import ModelFallbackPolicyError, run_with_model_chain

if TYPE_CHECKING:
    from collections.abc import Mapping

_PRIMARY = "anthropic/claude-opus"
_SECONDARY = "openai/gpt-5"
_TERTIARY = "google/gemini-3.1-pro-preview"

_XFAIL_HA2 = pytest.mark.xfail(reason="green after HA2.2: semantic fallback", strict=False)

_REVIEW_FAILED_REASONS = frozenset(
    {
        "provider_error",
        "timeout",
        "crash",
        "no_terminal_verdict",
        "malformed_submission",
        "semantic_rejection",
        "stale_attempt",
    }
)


def _chain_settings(
    *,
    allow_fallback: bool = True,
    models: list[str] | None = None,
) -> RepoSettings:
    return RepoSettings.model_validate(
        {
            "models": models if models is not None else [_PRIMARY, _SECONDARY],
            "allow_fallback": allow_fallback,
        }
    )


async def _run_chain(
    outcomes: Mapping[str, AgentResult],
    *,
    allow_fallback: bool = True,
    models: list[str] | None = None,
) -> tuple[str, AgentResult, list[str]]:
    """Drive ``run_with_model_chain`` with a slug → ``AgentResult`` script."""
    settings = _chain_settings(allow_fallback=allow_fallback, models=models)
    calls: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        calls.append(slug)
        return outcomes[slug]

    winner, result = await run_with_model_chain(settings=settings, run_once=run_once)
    return winner, result, calls


def _usable(*, submission_id: str, output: str = "reviewed") -> AgentResult:
    return AgentResult(
        success=True,
        output=output,
        terminal_submission_received=True,
        terminal_submission_id=submission_id,
    )


def _fallback_reason(result: AgentResult) -> object:
    return (result.metadata or {}).get("fallback_reason")


async def test_runtime_failure_still_triggers_fallback() -> None:
    """Regression pin: a retryable ``success=False`` still advances the chain."""
    winner, result, calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=False,
                error="provider unavailable",
                metadata={"retryable": True},
            ),
            _SECONDARY: _usable(submission_id="runtime-ok"),
        }
    )
    assert calls == [_PRIMARY, _SECONDARY]
    assert winner == _SECONDARY
    assert result.success is True
    assert result.terminal_submission_id == "runtime-ok"


@_XFAIL_HA2
async def test_provider_success_without_verdict_triggers_fallback() -> None:
    """H2 / D13 core: provider success without a terminal verdict must advance."""
    winner, result, calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=True,
                output="LGTM — looks good to me.",
                terminal_submission_received=False,
            ),
            _SECONDARY: _usable(submission_id="after-no-verdict"),
        }
    )
    assert calls == [_PRIMARY, _SECONDARY], (
        f"success=True without a terminal verdict must advance the chain, got {calls}"
    )
    assert winner == _SECONDARY
    assert result.terminal_submission_received is True
    assert result.terminal_submission_id == "after-no-verdict"


@_XFAIL_HA2
async def test_malformed_submission_triggers_fallback() -> None:
    """A schema-invalid submission is not a usable verdict — the chain advances."""
    from mergecraft.utils.agent_resolve import FallbackReason

    winner, result, calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=True,
                output="submitted a review",
                terminal_submission_received=False,
                diagnostics={
                    "malformed_submission": True,
                    "rejection_reason": "schema_invalid",
                },
            ),
            _SECONDARY: _usable(submission_id="after-malformed"),
        }
    )
    assert calls == [_PRIMARY, _SECONDARY], (
        f"malformed submission must advance the chain, got {calls}"
    )
    assert winner == _SECONDARY
    assert result.terminal_submission_id == "after-malformed"
    assert _fallback_reason(result) == FallbackReason.malformed_submission


async def test_valid_request_changes_does_not_trigger_fallback() -> None:
    """D13: a valid ``request_changes`` is a usable result — the chain must stop.

    Guard-deletion proof: after HA2.2, treating ``request_changes`` as
    incompletion (stamping ``no_terminal_verdict`` / ``semantic_rejection``,
    or advancing) must fail this test.
    """
    primary = AgentResult(
        success=True,
        output="Requesting changes: the auth path has no tests.",
        terminal_submission_received=True,
        terminal_submission_id="rc-1",
        diagnostics={
            "verdict": "request_changes",
            "summary": "The auth path has no tests.",
            "findings": [
                {
                    "path": "src/auth.py",
                    "severity": "major",
                    "message": "No tests for the new token check.",
                }
            ],
        },
    )
    winner, result, calls = await _run_chain(
        {
            _PRIMARY: primary,
            _SECONDARY: _usable(submission_id="must-not-run"),
        }
    )
    assert calls == [_PRIMARY], f"valid request_changes advanced the chain: {calls}"
    assert winner == _PRIMARY
    assert result.terminal_submission_received is True
    assert result.terminal_submission_id == "rc-1"
    assert result.metadata["fallback_index"] == 0
    assert result.metadata["fallback_occurred"] is False
    reason = _fallback_reason(result)
    assert reason != "no_terminal_verdict"
    assert reason != "semantic_rejection"


async def test_valid_approve_does_not_trigger_fallback() -> None:
    """A valid ``approve`` is a usable result — the chain must stop."""
    primary = AgentResult(
        success=True,
        output="Approve: no blocking issues in the diff.",
        terminal_submission_received=True,
        terminal_submission_id="ap-1",
        diagnostics={
            "verdict": "approve",
            "summary": "No blocking issues in the diff.",
            "findings": [],
        },
    )
    winner, result, calls = await _run_chain(
        {
            _PRIMARY: primary,
            _SECONDARY: _usable(submission_id="must-not-run"),
        }
    )
    assert calls == [_PRIMARY], f"valid approve advanced the chain: {calls}"
    assert winner == _PRIMARY
    assert result.terminal_submission_received is True
    assert result.terminal_submission_id == "ap-1"
    assert result.metadata["fallback_index"] == 0
    assert result.metadata["fallback_occurred"] is False
    reason = _fallback_reason(result)
    assert reason != "no_terminal_verdict"
    assert reason != "semantic_rejection"


@_XFAIL_HA2
async def test_fallback_reason_is_recorded_and_distinct() -> None:
    """Closed ``FallbackReason``: review-failed is not review-says-PR-fails (D13)."""
    from enum import Enum

    from mergecraft.utils.agent_resolve import FallbackReason

    assert issubclass(FallbackReason, Enum)
    values = {member.value for member in FallbackReason}
    assert values == _REVIEW_FAILED_REASONS
    assert "request_changes" not in values
    assert "approve" not in values
    assert FallbackReason.no_terminal_verdict != FallbackReason.semantic_rejection
    assert FallbackReason.no_terminal_verdict.value != FallbackReason.semantic_rejection.value

    winner, result, calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=True,
                output="prose only",
                terminal_submission_received=False,
            ),
            _SECONDARY: _usable(submission_id="reason-ok"),
        }
    )
    assert calls == [_PRIMARY, _SECONDARY]
    assert winner == _SECONDARY
    recorded = _fallback_reason(result)
    assert recorded == FallbackReason.no_terminal_verdict

    rc_winner, rc_result, rc_calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=True,
                output="Requesting changes.",
                terminal_submission_received=True,
                terminal_submission_id="rc-distinct",
                diagnostics={
                    "verdict": "request_changes",
                    "findings": [{"path": "src/auth.py", "message": "missing tests"}],
                },
            ),
            _SECONDARY: _usable(submission_id="must-not-run"),
        }
    )
    assert rc_calls == [_PRIMARY]
    assert rc_winner == _PRIMARY
    rc_reason = _fallback_reason(rc_result)
    assert rc_reason != FallbackReason.no_terminal_verdict
    assert rc_reason != FallbackReason.semantic_rejection

    fail_winner, fail_result, fail_calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=False,
                error="provider unavailable",
                metadata={"retryable": True},
            ),
            _SECONDARY: _usable(submission_id="after-provider-error"),
        }
    )
    assert fail_calls == [_PRIMARY, _SECONDARY]
    assert fail_winner == _SECONDARY
    fail_reason = _fallback_reason(fail_result)
    assert fail_reason == FallbackReason.provider_error
    assert fail_reason != FallbackReason.no_terminal_verdict
    assert fail_reason != FallbackReason.semantic_rejection


async def test_fallback_index_still_stamped() -> None:
    """Regression pin: ``_attach_model_evidence`` still stamps fallback metadata."""
    winner, result, calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=False,
                error="429 rate limited",
                metadata={"retryable": True},
            ),
            _SECONDARY: _usable(submission_id="stamped-ok"),
        }
    )
    assert calls == [_PRIMARY, _SECONDARY]
    assert winner == _SECONDARY
    meta = result.metadata
    assert meta["fallback_index"] == 1
    assert meta["fallback_occurred"] is True
    assert meta["requested_model"] == _PRIMARY
    assert meta["executed_model"] == _SECONDARY


async def test_allow_fallback_false_still_blocks() -> None:
    """Regression pin: ``allow_fallback=false`` still raises ``ModelFallbackPolicyError``."""
    calls: list[str] = []

    async def run_once(slug: str) -> AgentResult:
        calls.append(slug)
        return AgentResult(
            success=False,
            error="provider unavailable",
            metadata={"retryable": True},
        )

    with pytest.raises(ModelFallbackPolicyError, match=r"(?i)configuration|fallback"):
        await run_with_model_chain(
            settings=_chain_settings(allow_fallback=False),
            run_once=run_once,
        )
    assert calls == [_PRIMARY], f"chain advanced despite allow_fallback=false: {calls}"


@_XFAIL_HA2
async def test_stale_primary_result_is_not_reused_by_fallback() -> None:
    """A result whose attempt id does not match the current attempt is not reused.

    HA2 surface (VP3 types may not exist yet): ``fallback_reason`` is
    ``stale_attempt`` and the returned ``AgentResult`` is not the stale object.
    """
    from mergecraft.utils.agent_resolve import FallbackReason

    stale = AgentResult(
        success=True,
        output="cached review from attempt 0",
        terminal_submission_received=True,
        terminal_submission_id="attempt-0-submission",
        diagnostics={"attempt_id": 0},
    )
    fresh = AgentResult(
        success=True,
        output="fresh review",
        terminal_submission_received=True,
        terminal_submission_id="attempt-2-submission",
        diagnostics={"attempt_id": 2},
    )
    winner, result, calls = await _run_chain(
        {
            _PRIMARY: AgentResult(
                success=False,
                error="crash",
                metadata={"retryable": True},
            ),
            _SECONDARY: stale,
            _TERTIARY: fresh,
        },
        models=[_PRIMARY, _SECONDARY, _TERTIARY],
    )
    assert calls == [_PRIMARY, _SECONDARY, _TERTIARY], (
        f"stale AgentResult must not satisfy the current attempt, got {calls}"
    )
    assert result is not stale
    assert winner == _TERTIARY
    assert result.terminal_submission_id == "attempt-2-submission"
    assert _fallback_reason(result) == FallbackReason.stale_attempt


@_XFAIL_HA2
async def test_both_harnesses_obey_the_rule() -> None:
    """OpenCode-shaped and Codex-shaped incomplete results reach the same decision."""
    incomplete = {
        "opencode": AgentResult(
            success=True,
            output="opencode session completed",
            usage=AgentUsage(agent="opencode", input_tokens=10, output_tokens=4),
            terminal_submission_received=False,
        ),
        "codex": AgentResult(
            success=True,
            output="codex CLI completed",
            usage=AgentUsage(agent="codex", input_tokens=12, output_tokens=6),
            terminal_submission_received=False,
        ),
    }
    for harness, primary in incomplete.items():
        winner, result, calls = await _run_chain(
            {
                _PRIMARY: primary,
                _SECONDARY: _usable(submission_id=f"{harness}-ok", output=f"{harness} reviewed"),
            }
        )
        assert calls == [_PRIMARY, _SECONDARY], (
            f"{harness}-shaped success without a terminal verdict must advance, got {calls}"
        )
        assert winner == _SECONDARY
        assert result.terminal_submission_received is True
        assert result.terminal_submission_id == f"{harness}-ok"
