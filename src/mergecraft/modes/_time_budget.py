"""Agent time budget: the prompt's ``${TIME_BUDGET}`` line and the live elapsed notice.

The prompt tells the agent to stop exploring at ~60% of its deadline and to
submit at ~80%, but the agent has no clock. The MCP server therefore appends
an elapsed/remaining notice to tool results once a run crosses the first
checkpoint. Both texts read their thresholds from here so they cannot drift.

Module: mergecraft.modes._time_budget
Depends: (none)

Exports:
    STOP_EXPLORING_FRACTION — Share of the deadline after which exploring stops.
    SUBMIT_FRACTION — Share of the deadline by which the verdict is submitted.
    render_time_budget — The ``${TIME_BUDGET}`` marker text.
    elapsed_notice — The tool-result notice for an elapsed share, or ``None``.
"""

from __future__ import annotations

from typing import Final

STOP_EXPLORING_FRACTION: Final[float] = 0.6
SUBMIT_FRACTION: Final[float] = 0.8

_STOP_EXPLORING = "stop exploring and move to verification and drafting findings"


def render_time_budget(time_budget_minutes: int | None) -> str:
    """Render the ``${TIME_BUDGET}`` marker for the agent's deadline.

    ``time_budget_minutes`` is the agent deadline the harness enforces (the run
    timeout minus setup elapsed). The checkpoints are where the agent must stop
    exploring and then submit; without them a slow run spends its whole budget
    exploring and is killed with no verdict. ``None`` (no deadline) renders a
    neutral line, so no rendered prompt keeps a ``${...}`` sequence.
    """
    if time_budget_minutes is None:
        return (
            "this run has no fixed time limit, but keep exploration proportional to risk: "
            "once your open questions are answered or ruled out, move to verification and "
            "drafting findings."
        )
    minutes = max(1, time_budget_minutes)
    stop_exploring = max(1, round(minutes * STOP_EXPLORING_FRACTION))
    submit_by = max(1, round(minutes * SUBMIT_FRACTION))
    return (
        f"you have about {minutes} minutes for this run. By about minute {stop_exploring} "
        f"(~{STOP_EXPLORING_FRACTION:.0%} of it), {_STOP_EXPLORING}. "
        f"By about minute {submit_by} (~{SUBMIT_FRACTION:.0%}), submit the verdict with what "
        "you have; an unconfirmed concern goes in at lower severity or in the summary, not as "
        "a reason to keep exploring. Once you pass the first checkpoint, tool results carry a "
        "⏱ notice with the minutes used and left — a `timeBudget` field on JSON results, so "
        "keep it when you return only part of a result."
    )


def elapsed_notice(elapsed_s: float, deadline_s: float) -> str | None:
    """Return the ⏱ notice for ``elapsed_s`` of a ``deadline_s`` budget, or ``None``.

    ``None`` below the stop-exploring checkpoint, so early tool results are
    unchanged. Minutes are whole and floored, matching the prompt's budget.
    """
    if deadline_s <= 0 or elapsed_s < deadline_s * STOP_EXPLORING_FRACTION:
        return None
    total = max(1, int(deadline_s // 60))
    used = min(total, int(elapsed_s // 60))
    left = total - used
    head = f"⏱ {used} of {total} min used, about {left} left: "
    if elapsed_s >= deadline_s * SUBMIT_FRACTION:
        return head + "submit the verdict now with what you have."
    return head + _STOP_EXPLORING + "."


__all__ = [
    "STOP_EXPLORING_FRACTION",
    "SUBMIT_FRACTION",
    "elapsed_notice",
    "render_time_budget",
]
