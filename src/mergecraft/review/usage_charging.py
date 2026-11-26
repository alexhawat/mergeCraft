"""Charge a dispatched reviewer's usage to the run (issue #1559).

Every provider dispatch — the primary reviewer, each secondary roster reviewer and
each file-group reviewer — spends tokens the run has to account for. The primary
paths already priced, listed and charged their usage inline; the roster and
file-group dispatches share :func:`mergecraft.review.roster_execution._dispatch_reviewer`,
which never read ``AgentResult.usage``.

Exports:
    charge_reviewer_usage: Price, list and charge one dispatch's usage, in order.
    observed_stream_usage: The partial usage one dispatch's stream reported.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.curated_model_catalog import apply_catalog_cost_to_usage
from mergecraft.utils.run_bounds import record_agent_usage

if TYPE_CHECKING:
    from mergecraft.agents.shared import AgentUsage
    from mergecraft.mcp.tool_state import ToolState
    from mergecraft.utils.run_bounds import BudgetTracker, StreamCharges

__all__ = ["charge_reviewer_usage", "observed_stream_usage"]


def charge_reviewer_usage(
    *,
    tool_state: ToolState,
    budget_tracker: BudgetTracker | None,
    usage: AgentUsage | None,
    model: str | None,
    phase: str = "reviewer_dispatch",
    streamed: StreamCharges | None = None,
) -> AgentUsage | None:
    """Price, list and charge one reviewer dispatch's usage, in that order.

    The steps are ordered because the run's reported cost and its budget both
    read the same priced row:

    1. price the usage with :func:`apply_catalog_cost_to_usage` for ``model``
       (a provider that reported no ``cost_usd`` gets the catalog rate);
    2. append the priced usage to ``tool_state.usage_entries`` — the list the
       published cost and token summaries are built from;
    3. charge it with :func:`record_agent_usage`, so the run's token and cost
       budgets see the dispatch.

    A ``None`` usage is a no-op and returns ``None``: a reviewer that reported
    nothing is neither listed nor charged. ``BudgetExhausted`` from step 3 is
    **not** caught here — the caller decides whether the overrun ends the run.

    Args:
        tool_state: The run's tool state; its ``usage_entries`` receives the row.
        budget_tracker: The run's budget tracker, or ``None`` when the caller has
            no per-run budget.
        usage: The dispatch's reported usage, or ``None`` when it reported none.
        model: The model the dispatch executed, used to price missing cost.
        phase: Usage-breakdown label recorded with the charge.
        streamed: What this dispatch's stream already charged; the charge adds
            only the remainder.

    Returns:
        The priced usage that was appended, or ``None`` for a ``None`` input.

    Raises:
        BudgetExhausted: Charging the usage crossed the run's budget ceiling. The
            caller decides what that means for the run; this helper never
            swallows it.

    Examples:
        >>> from mergecraft.agents.shared import AgentUsage
        >>> from mergecraft.mcp.tool_state import init_tool_state
        >>> state = init_tool_state(owner="acme", name="demo", dir=".")
        >>> priced = charge_reviewer_usage(
        ...     tool_state=state,
        ...     budget_tracker=None,
        ...     usage=AgentUsage(agent="opencode", input_tokens=10, output_tokens=5),
        ...     model="acme/unlisted-model",
        ... )
        >>> state.usage_entries == [priced]
        True
    """
    priced = apply_catalog_cost_to_usage(usage, model=model)
    if priced is None:
        return None
    tool_state.usage_entries.append(priced)
    record_agent_usage(budget_tracker, priced, phase=phase, streamed=streamed)
    return priced


def observed_stream_usage(streamed: StreamCharges | None, *, agent: str) -> AgentUsage | None:
    """Return what one dispatch's stream reported, for a dispatch that ended abnormally.

    A reviewer that times out or raises never returns its final ``AgentUsage``,
    but the steps it streamed were already charged to the run (#1588). This is
    that observed spend as a usage row, so it can be listed once and attributed
    to the reviewer instead of surfacing as an unexplained residual.

    Args:
        streamed: The dispatch's own stream charges, or ``None``.
        agent: The harness name the row is attributed to.

    Returns:
        The observed usage, or ``None`` when the stream reported no usage: an
        unknown spend stays unknown and no estimate is made up for it.

    Examples:
        >>> from mergecraft.utils.run_bounds import StreamCharges
        >>> observed_stream_usage(StreamCharges(), agent="opencode") is None
        True
        >>> row = observed_stream_usage(
        ...     StreamCharges(tokens=30, cost_usd=0.2, input_tokens=20, output_tokens=10),
        ...     agent="opencode",
        ... )
        >>> (row.input_tokens, row.output_tokens, row.cost_usd)
        (20, 10, 0.2)
    """
    from mergecraft.agents.shared import AgentUsage

    if streamed is None:
        return None
    if not (streamed.input_tokens or streamed.output_tokens or streamed.cost_usd > 0):
        return None
    return AgentUsage(
        agent=agent,
        input_tokens=streamed.input_tokens,
        output_tokens=streamed.output_tokens,
        cache_read_tokens=streamed.cache_read_tokens or None,
        cache_write_tokens=streamed.cache_write_tokens or None,
        cost_usd=streamed.cost_usd if streamed.cost_usd > 0 else None,
    )
