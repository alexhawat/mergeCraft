"""Shared run-outcome input assembly."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from mergecraft.review.outcome_resolution import (
    resolve_run_outcome,
    roster_failure_from_result,
)

if TYPE_CHECKING:
    from mergecraft.review.outcome_resolution import OutcomeInputs
    from mergecraft.run_outcome import RunOutcome
    from mergecraft.utils.run_bounds import BudgetTracker


def complete_outcome_inputs(
    inputs: OutcomeInputs,
    *,
    budget_tracker: BudgetTracker | None,
) -> OutcomeInputs:
    """Read required roster failure and exhausted budgets for the outcome resolver.

    The MCP handler catches a budget exhaustion before replying to the tool
    caller. The tracker retains the exception so finalize can still report it.

    Args:
        inputs: Outcome inputs assembled by the entry point.
        budget_tracker: The run's MCP budget tracker, when present.

    Returns:
        Inputs with required roster status and the first recorded exhaustion.
    """
    budget_exhaustion = inputs.budget_exhaustion
    if budget_exhaustion is None and budget_tracker is not None:
        budget_exhaustion = getattr(budget_tracker, "last_exhausted", None)
    roster_failure, roster_infra_reason = roster_failure_from_result(inputs.result)
    return replace(
        inputs,
        budget_exhaustion=budget_exhaustion,
        roster_failure=roster_failure,
        roster_infra_reason=roster_infra_reason,
    )


@dataclass(frozen=True, slots=True)
class ReviewFinalization:
    """Outcome and failure reason resolved before writing the run evidence."""

    outcome: RunOutcome
    failure_reason: str | None


def finalize_review_outcome(inputs: OutcomeInputs) -> ReviewFinalization:
    """Resolve the completed run, including the entry point's publication signals.

    Args:
        inputs: Run-level gates and outcomes available at finalization.

    Returns:
        The outcome and reason ready for evidence publication.
    """
    outcome, failure_reason = resolve_run_outcome(inputs)
    return ReviewFinalization(outcome, failure_reason)
