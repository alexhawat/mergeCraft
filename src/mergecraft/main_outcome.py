"""Outcome-resolution helpers used by ``main.py``.

Extracted from ``main.py`` so the orchestrator stays under the 1k-line ceiling.
Both helpers carry over verbatim — the audit confirmed ``NO_ISSUES`` on the
``_classify_outcome`` resolver (D3/W5.2 + S1/D5/D10) and the
``_publish_span_attrs`` span-attr builder (#145).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.run_outcome import RunOutcome
from mergecraft.tracing.event import trace_attrs_for_mode

if TYPE_CHECKING:
    from mergecraft.action.inputs import SetupFailurePolicy
    from mergecraft.agents.shared import AgentResult
    from mergecraft.modes import Mode


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
) -> tuple[RunOutcome, str | None]:
    """Map the run's result + side-channels to a ``RunOutcome`` (D3/W5.2 + S1/D5/D10).

    Mirrors the inline resolver that lived at the bottom of :func:`main`.
    Returns ``(outcome, failure_reason)``. The four branches are:
    ``result.success is False`` -> ``RunOutcome.failed``; trusted-tier
    ``setup_script`` failure under ``setup_failure_policy == "fail"`` ->
    ``RunOutcome.configuration_error``; same under
    ``setup_failure_policy == "inconclusive"`` -> ``RunOutcome.inconclusive``;
    review-relevant dependency-prep failure -> ``RunOutcome.inconclusive``;
    otherwise (the closed ``SetupFailurePolicy`` value ``"warn"`` or no
    failure surface) -> ``RunOutcome.passed``. Each non-pass branch logs a
    warning here so the call site only needs the tuple.
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
    # ``setup_policy`` is the closed ``SetupFailurePolicy`` vocabulary; any
    # value other than ``fail`` / ``inconclusive`` (i.e. ``warn``, or the
    # Pydantic default the action-input resolver accepted) means "proceed
    # even if the setup script reported a failure".
    return RunOutcome.passed, None


__all__ = ["_classify_outcome", "_publish_span_attrs"]
