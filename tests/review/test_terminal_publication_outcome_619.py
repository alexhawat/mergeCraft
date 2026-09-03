"""#619 Task 3 — a recorded-but-unpublished terminal verdict fails closed.

On PR #619 ``create_pull_request_review`` 422'd three times and the review
never published, yet the run still reported ``RunOutcome.passed``. This
suite pins two things:

(a) ``_classify_outcome`` maps ``terminal_publication_failed=True`` to
    ``RunOutcome.inconclusive`` for a review-mode run, with a reason
    distinct from "no verdict was submitted at all" — and
    ``run_succeeded_for_outcome`` on that outcome is ``False``, which is
    what keeps ``mergecraft-approval`` from posting ``success`` (the check
    is driven by ``packet.decision.verdict``, and the packet is built with
    ``run_succeeded=run_succeeded_for_outcome(outcome)``).
(b) ``mergecraft.evidence.shadow.predict_verdict_protocol`` agrees: the
    ``mergecraft.publish`` span's ``VerdictDiagnostic`` is
    ``terminal_submission_unpublished``, not ``approved``.
"""

from __future__ import annotations

from mergecraft.agents.shared import AgentResult
from mergecraft.main_outcome import (
    _MISSING_TERMINAL_VERDICT_REASON,
    _UNPUBLISHED_TERMINAL_VERDICT_REASON,
    _classify_outcome,
)
from mergecraft.run_outcome import RunOutcome, run_succeeded_for_outcome


def _classify(
    result: AgentResult,
    *,
    mode: str = "Review",
    terminal_publication_failed: bool = False,
) -> tuple[RunOutcome, str | None]:
    return _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode,
        terminal_publication_failed=terminal_publication_failed,
    )


def test_unpublished_terminal_submission_is_inconclusive_not_passed() -> None:
    """A recorded verdict that never published must not read as a clean run."""
    result = AgentResult(
        success=True,
        terminal_submission_received=True,
        terminal_submission_id="sub-619",
    )
    outcome, reason = _classify(result, terminal_publication_failed=True)

    assert outcome is RunOutcome.inconclusive
    assert outcome is not RunOutcome.passed
    assert reason == _UNPUBLISHED_TERMINAL_VERDICT_REASON
    assert reason != _MISSING_TERMINAL_VERDICT_REASON
    assert run_succeeded_for_outcome(outcome) is False


def test_unpublished_reason_is_distinct_from_missing_verdict_reason() -> None:
    """Both are ``inconclusive``, but the reasons name different failures."""
    unpublished, unpublished_reason = _classify(
        AgentResult(success=True, terminal_submission_received=True),
        terminal_publication_failed=True,
    )
    missing, missing_reason = _classify(
        AgentResult(success=True, terminal_submission_received=False),
        terminal_publication_failed=False,
    )

    assert unpublished is RunOutcome.inconclusive
    assert missing is RunOutcome.inconclusive
    assert unpublished_reason != missing_reason
    assert "published" in unpublished_reason
    assert "submitted" in missing_reason


def test_publication_failure_flag_is_a_noop_outside_review_mode() -> None:
    """The flag only matters for review-mode runs — a non-review mode ignores it."""
    result = AgentResult(success=True, terminal_submission_received=True)
    outcome, reason = _classify(result, mode="SomeOtherMode", terminal_publication_failed=True)
    assert outcome is RunOutcome.passed
    assert reason is None


def test_successful_publication_still_passes() -> None:
    """Green guard: a run that published cleanly is unaffected."""
    result = AgentResult(
        success=True,
        terminal_submission_received=True,
        terminal_submission_id="sub-clean",
    )
    outcome, reason = _classify(result, terminal_publication_failed=False)
    assert outcome is RunOutcome.passed
    assert reason is None
    assert run_succeeded_for_outcome(outcome) is True


def test_shadow_prediction_agrees_with_unpublished_outcome() -> None:
    """The ``mergecraft.publish`` span's diagnostic must not disagree with the outcome."""
    from mergecraft.evidence.shadow import predict_verdict_protocol
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = AgentResult(
        success=True,
        terminal_submission_received=True,
        terminal_submission_id="sub-619",
    )
    prediction = predict_verdict_protocol(
        result,
        mode="Review",
        terminal_publication_failed=True,
    )

    assert prediction.outcome is RunOutcome.inconclusive
    assert prediction.diagnostic == VerdictDiagnostic.terminal_submission_unpublished.value
    assert prediction.diagnostic != VerdictDiagnostic.approved.value


def test_shadow_prediction_unaffected_when_publication_did_not_fail() -> None:
    """Green guard for the shadow predictor."""
    from mergecraft.evidence.shadow import predict_verdict_protocol
    from mergecraft.mcp.verdict import VerdictDiagnostic

    result = AgentResult(
        success=True,
        terminal_submission_received=True,
        terminal_submission_id="sub-clean",
    )
    prediction = predict_verdict_protocol(result, mode="Review", terminal_publication_failed=False)
    assert prediction.outcome is RunOutcome.passed
    assert prediction.diagnostic == VerdictDiagnostic.approved.value
