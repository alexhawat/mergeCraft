"""Outcome-resolution helpers used by ``main.py``.

Extracted from ``main.py`` so the orchestrator stays under the 1k-line ceiling.
Both helpers carry over verbatim — the audit confirmed ``NO_ISSUES`` on the
``_classify_outcome`` resolver (D3/W5.2 + S1/D5/D10) and the
``_publish_span_attrs`` span-attr builder (#145).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, NamedTuple

from loguru import logger

from mergecraft.run_outcome import RunOutcome
from mergecraft.tracing.event import trace_attrs_for_mode

if TYPE_CHECKING:
    from mergecraft.action.inputs import SetupFailurePolicy
    from mergecraft.agents.shared import AgentResult
    from mergecraft.evidence.shadow import VerdictProtocolPrediction
    from mergecraft.mcp.verdict import VerdictDiagnostic
    from mergecraft.modes import Mode


class VerdictProtocolPublish(NamedTuple):
    """What the publish seam needs from one verdict-protocol prediction.

    ``diagnostic`` is carried as the enum rather than re-read out of ``attrs``:
    the span attrs are a redacted, stringly-typed payload, so digging the code
    back out of them loses the closed vocabulary the predictor already resolved.
    """

    attrs: dict[str, Any]
    diagnostic: VerdictDiagnostic
    prediction: VerdictProtocolPrediction | None


_REVIEW_MODE_NAMES = frozenset({"Review", "IncrementalReview"})
_INCREMENTAL_REVIEW_NAMES = frozenset({"IncrementalReview"})
_MISSING_TERMINAL_VERDICT_REASON = "no terminal review verdict was submitted for this attempt"
# #619 Task 3a — a distinct reason from the one above: the agent *did* record
# a terminal verdict, but the review that carries it never reached GitHub
# (every 422 recovery attempt failed; see
# ``mcp/review.py::_create_github_review_with_anchor_recovery``). #619 hit
# exactly this: ``create_pull_request_review`` 422'd three times and the run
# still reported ``RunOutcome.passed`` because nothing downstream of the
# publish call distinguished "never tried" from "tried and lost the review".
_UNPUBLISHED_TERMINAL_VERDICT_REASON = (
    "terminal review verdict was recorded but never published to GitHub"
)


def _is_review_mode(mode: str | Mode | None) -> bool:
    if mode is None:
        return False
    if isinstance(mode, str):
        return mode in _REVIEW_MODE_NAMES
    return mode.name in _REVIEW_MODE_NAMES


def _is_incremental_review(mode: str | Mode | None) -> bool:
    if mode is None:
        return False
    name = mode if isinstance(mode, str) else mode.name
    return name in _INCREMENTAL_REVIEW_NAMES


def _publish_span_attrs(outcome: RunOutcome, mode: Mode | None) -> dict[str, Any]:
    """Build the attrs dict the ``mergecraft.publish`` span emits.

    #145 contract: the selected mode's prompt version reaches the trace
    so a Logfire/OTel row carries the prompt name and version of the
    mode that actually ran, even when the prompt text changes later.
    """
    return {"run_succeeded": outcome is RunOutcome.passed} | (
        trace_attrs_for_mode(mode) if mode else {}
    )


def _classify_outcome(
    *,
    result: AgentResult,
    setup_reason: str,
    setup_policy: SetupFailurePolicy,
    prep_reason: str | None,
    mode: str | Mode | None = None,
    verdict_protocol: Literal["shadow", "enforce"] | None = None,
    final_summary_written: bool = False,
    terminal_publication_failed: bool = False,
) -> tuple[RunOutcome, str | None]:
    """Map the run's result + side-channels to a ``RunOutcome`` (D3/W5.2 + S1/D5/D10).

    Mirrors the inline resolver that lived at the bottom of :func:`main`.
    Returns ``(outcome, failure_reason)``. The branches are:
    ``result.success is False`` -> ``RunOutcome.failed``; trusted-tier
    ``setup_script`` failure under ``setup_failure_policy == "fail"`` ->
    ``RunOutcome.configuration_error``; same under
    ``setup_failure_policy == "inconclusive"`` -> ``RunOutcome.inconclusive``;
    review-relevant dependency-prep failure -> ``RunOutcome.inconclusive``;
    a review-mode run whose terminal submission never reached GitHub
    (``terminal_publication_failed``) -> ``RunOutcome.inconclusive`` (#619
    Task 3a — a *recorded* verdict that never published must not read as a
    clean run); a review-mode run with no terminal submission at all ->
    ``RunOutcome.inconclusive``; otherwise (the closed ``SetupFailurePolicy``
    value ``"warn"`` or no failure surface) -> ``RunOutcome.passed``. Each
    non-pass branch logs a warning here so the call site only needs the tuple.
    """
    if not result.success:
        return RunOutcome.failed, result.error
    if setup_reason and setup_policy == "fail":
        # D10 ``fail`` — operator has declared the failure is unrecoverable.
        logger.warning(
            "» setup script failure mapped run to configuration_error (fail policy): {}",
            setup_reason,
        )
        return RunOutcome.configuration_error, setup_reason
    if setup_reason and setup_policy == "inconclusive":
        # D5 / D10 default — under-provisioned tree is no-verdict.
        logger.warning("» setup script failure mapped run to inconclusive: {}", setup_reason)
        return RunOutcome.inconclusive, setup_reason
    if prep_reason:
        logger.warning("» prep failure mapped run to inconclusive: {}", prep_reason)
        return RunOutcome.inconclusive, prep_reason
    if _is_review_mode(mode) and terminal_publication_failed and verdict_protocol != "shadow":
        logger.warning("» {}", _UNPUBLISHED_TERMINAL_VERDICT_REASON)
        return RunOutcome.inconclusive, _UNPUBLISHED_TERMINAL_VERDICT_REASON
    if (
        _is_review_mode(mode)
        and not result.terminal_submission_received
        and verdict_protocol != "shadow"
    ):
        if _is_incremental_review(mode) and final_summary_written:
            return RunOutcome.passed, None
        logger.warning("» {}", _MISSING_TERMINAL_VERDICT_REASON)
        return RunOutcome.inconclusive, _MISSING_TERMINAL_VERDICT_REASON
    # ``setup_policy`` is the closed ``SetupFailurePolicy`` vocabulary; any
    # value other than ``fail`` / ``inconclusive`` (i.e. ``warn``, or the
    # Pydantic default the action-input resolver accepted) means "proceed
    # even if the setup script reported a failure".
    return RunOutcome.passed, None


def _verdict_protocol_publish(
    *,
    result: AgentResult,
    mode: str | Mode | None,
    setup_reason: str,
    setup_policy: SetupFailurePolicy,
    prep_reason: str | None,
    final_summary_written: bool,
    terminal_verdict: str,
    terminal_publication_failed: bool = False,
) -> VerdictProtocolPublish:
    """Predict the enforce-path verdict protocol and build publish span attrs.

    The prediction is always computed so the ``mergecraft.publish`` span
    carries a closed ``VerdictDiagnostic``. The shadow recorder only
    receives the prediction when ``terminal_verdict == "shadow"``.
    """
    from mergecraft.evidence.shadow import predict_verdict_protocol
    from mergecraft.mcp.verdict import VerdictDiagnostic, span_attrs_for_verdict_diagnostic

    mode_name = mode if isinstance(mode, str) else (mode.name if mode is not None else "")
    prediction = predict_verdict_protocol(
        result,
        mode=mode_name,
        setup_reason=setup_reason,
        setup_policy=str(setup_policy),
        prep_reason=prep_reason,
        final_summary_written=final_summary_written,
        terminal_publication_failed=terminal_publication_failed,
    )
    diagnostic = VerdictDiagnostic(prediction.diagnostic)
    attrs = span_attrs_for_verdict_diagnostic(diagnostic, summary=result.output or "")
    return VerdictProtocolPublish(
        attrs=attrs,
        diagnostic=diagnostic,
        prediction=prediction if terminal_verdict == "shadow" else None,
    )


__all__ = [
    "VerdictProtocolPublish",
    "_classify_outcome",
    "_is_review_mode",
    "_publish_span_attrs",
    "_verdict_protocol_publish",
]
