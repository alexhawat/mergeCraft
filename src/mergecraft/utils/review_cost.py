"""Measure the reviewer model costs recorded for a run.

Exports: `RecordedRunCost`, `recorded_run_cost`.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class RecordedRunCost:
    """Recorded USD amount, coverage of recorded attempts, and billing notes."""

    amount_usd: float | None
    availability: Literal["available", "partial", "unavailable"]
    notes: tuple[str, ...]


def recorded_run_cost(
    usage_entries: Sequence[object],
    *,
    budget_tracker: object | None = None,
) -> RecordedRunCost:
    """Measure reported and estimated reviewer model costs.

    The tracker and usage entries can cover the same costs. Prefer the higher
    recorded total because token exhaustion can interrupt tracker accounting
    after the usage entry has already been saved.

    Args:
        usage_entries: Recorded reviewer attempts, in dispatch order.
        budget_tracker: Optional tracker for this run's costs.

    Returns:
        A finite recorded amount when available, with coverage and notes.
    """
    from mergecraft.agents.shared import AgentUsage
    from mergecraft.utils.run_bounds import BudgetTracker

    amounts: list[float] = []
    notes: dict[str, None] = {}
    missing = False
    for entry in usage_entries:
        if not isinstance(entry, AgentUsage):
            missing = True
            continue
        amount = entry.cost_usd
        if amount is None or not isfinite(amount) or amount < 0:
            missing = True
        else:
            amounts.append(max(0.0, amount))
        if entry.cost_note:
            notes[entry.cost_note] = None

    total = sum(amounts, 0.0)
    if not isfinite(total):
        return RecordedRunCost(None, "unavailable", tuple(notes))
    tracked = budget_tracker.cost_used if isinstance(budget_tracker, BudgetTracker) else 0.0
    if isfinite(tracked) and tracked > 0.0:
        total = max(total, tracked)
    elif not amounts:
        return RecordedRunCost(None, "unavailable", tuple(notes))

    return RecordedRunCost(total, "partial" if missing else "available", tuple(notes))
