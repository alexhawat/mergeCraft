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

from typing import Any, Literal

import pytest

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


# ── a recorded verdict that never reached GitHub, and one that differs ───────
#
# Two new classifier inputs, both defaulting to "not applicable" so the offline
# classifier (``review/offline_agent.py``) is unchanged:
#
# ``terminal_publication_receipt``: ``None`` (not applicable), ``True`` (a
# receipt for the recorded verdict exists), ``False`` (no receipt).
# ``terminal_publication_mismatch``: ``None``, or ``(published_verdict,
# recorded_verdict)`` when GitHub shows a different verdict than the one the
# run recorded.


def _classify_publication(
    result: AgentResult,
    *,
    mode: str = "Review",
    verdict_protocol: Literal["shadow", "enforce"] | None = None,
    **publication: Any,
) -> tuple[RunOutcome, str | None]:
    return _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode=mode,
        verdict_protocol=verdict_protocol,
        **publication,
    )


def _received() -> AgentResult:
    return AgentResult(success=True, terminal_submission_received=True, terminal_submission_id="s")


@pytest.mark.parametrize("mode", ["Review", "IncrementalReview"])
def test_recorded_verdict_without_a_receipt_is_inconclusive_with_its_own_reason(
    mode: str,
) -> None:
    """Error: a received submission with no receipt is not a clean run (and says why)."""
    outcome, reason = _classify_publication(
        _received(), mode=mode, terminal_publication_receipt=False
    )

    assert outcome is RunOutcome.inconclusive
    assert reason is not None
    assert reason not in {_MISSING_TERMINAL_VERDICT_REASON, _UNPUBLISHED_TERMINAL_VERDICT_REASON}
    assert "publish" in reason.lower()
    assert run_succeeded_for_outcome(outcome) is False


def test_recorded_verdict_with_a_receipt_passes() -> None:
    """Happy path: the receipt exists for the recorded verdict."""
    outcome, reason = _classify_publication(_received(), terminal_publication_receipt=True)
    assert outcome is RunOutcome.passed
    assert reason is None


def test_missing_receipt_is_ignored_in_shadow_mode() -> None:
    """Edge: the shadow protocol never publishes from the run, so no receipt is expected."""
    outcome, reason = _classify_publication(
        _received(), verdict_protocol="shadow", terminal_publication_receipt=False
    )
    assert outcome is RunOutcome.passed
    assert reason is None


def test_missing_receipt_is_ignored_outside_review_modes() -> None:
    """Edge: only review modes publish a verdict."""
    outcome, reason = _classify_publication(
        _received(), mode="Plan", terminal_publication_receipt=False
    )
    assert outcome is RunOutcome.passed
    assert reason is None


def test_publication_failure_keeps_its_own_reason_over_a_missing_receipt() -> None:
    """Ordering: a failed POST is reported as the failure, not as "never attempted"."""
    outcome, reason = _classify_publication(
        _received(),
        terminal_publication_failed=True,
        terminal_publication_receipt=False,
    )
    assert outcome is RunOutcome.inconclusive
    assert reason == _UNPUBLISHED_TERMINAL_VERDICT_REASON


def test_no_submission_keeps_the_missing_verdict_reason() -> None:
    """Ordering: with nothing recorded, the missing-verdict reason still wins."""
    outcome, reason = _classify_publication(
        AgentResult(success=True, terminal_submission_received=False),
        terminal_publication_receipt=False,
    )
    assert outcome is RunOutcome.inconclusive
    assert reason == _MISSING_TERMINAL_VERDICT_REASON


@pytest.mark.parametrize(
    ("published", "recorded"),
    [("request_changes", "approve"), ("approve", "request_changes")],
)
def test_verdict_mismatch_is_inconclusive_and_names_both_verdicts(
    published: str, recorded: str
) -> None:
    """Error: GitHub shows a different verdict than the run recorded -> say both."""
    outcome, reason = _classify_publication(
        _received(),
        terminal_publication_receipt=True,
        terminal_publication_mismatch=(published, recorded),
    )

    assert outcome is RunOutcome.inconclusive
    assert reason is not None
    assert published in reason
    assert recorded in reason
    assert reason not in {_MISSING_TERMINAL_VERDICT_REASON, _UNPUBLISHED_TERMINAL_VERDICT_REASON}


def test_offline_classification_is_unchanged() -> None:
    """Green guard: the offline call shape (no publication inputs) still passes a received run.

    ``review/offline_agent.py`` classifies with exactly these arguments and
    never publishes; the new inputs default to "not applicable".
    """
    outcome, reason = _classify_outcome(
        result=_received(),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode="Review",
        verdict_protocol="enforce",
    )
    assert outcome is RunOutcome.passed
    assert reason is None


@pytest.mark.parametrize(
    "publication",
    [
        {"terminal_publication_receipt": False},
        {
            "terminal_publication_receipt": True,
            "terminal_publication_mismatch": ("request_changes", "approve"),
        },
    ],
    ids=["no_receipt", "mismatch"],
)
def test_shadow_prediction_agrees_with_the_new_publication_outcomes(
    publication: dict[str, Any],
) -> None:
    """The ``mergecraft.publish`` span's diagnostic must not disagree with the outcome."""
    from mergecraft.evidence.shadow import predict_verdict_protocol
    from mergecraft.mcp.verdict import VerdictDiagnostic

    outcome, _reason = _classify_publication(_received(), **publication)
    prediction = predict_verdict_protocol(_received(), mode="Review", **publication)

    assert outcome is RunOutcome.inconclusive
    assert prediction.outcome is outcome
    assert prediction.diagnostic != VerdictDiagnostic.approved.value
