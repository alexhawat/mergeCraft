"""Per-step token charging for streaming reviewer drivers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker

if TYPE_CHECKING:
    from mergecraft.jev.cost import TokenBudget

_PHASE = "reviewer_dispatch"


def token_total_from_usage_payload(payload: Mapping[str, Any]) -> int:
    """Return billed tokens for one usage payload using ``AgentUsage`` rules."""
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator

    accumulator = StreamSpanAccumulator(agent_name="budget")
    accumulator.absorb_usage(payload)
    usage = accumulator.to_usage()
    if usage is None:
        return 0
    return usage.input_tokens + usage.output_tokens


def charge_review_stream_step(
    payload: Mapping[str, Any],
    *,
    budget_tracker: BudgetTracker | None,
    provider_budget: TokenBudget | None,
    cost_usd: float | None = None,
) -> str | None:
    """Charge one stream step against run bounds; return a stop reason when over ceiling.

    Returns:
        ``None`` when the step was accepted. A human-readable reason when the run
        must stop before spending further provider tokens.
    """
    count = token_total_from_usage_payload(payload)
    if count <= 0 and (cost_usd is None or cost_usd <= 0):
        return None

    if budget_tracker is not None and count > 0:
        try:
            budget_tracker.record_tokens_stream_increment(count, phase=_PHASE)
            budget_tracker.stream_tokens_charged += count
        except BudgetExhausted as exc:
            return str(exc)

    if provider_budget is not None and count > 0:
        from mergecraft.agents.token_budget import record_provider_usage

        if not record_provider_usage(
            provider_budget,
            input_tokens=count,
            output_tokens=0,
        ):
            return provider_budget.stop_reason or "budget"

    if budget_tracker is not None and cost_usd is not None and cost_usd > 0:
        try:
            budget_tracker.record_cost(cost_usd)
        except BudgetExhausted as exc:
            return str(exc)
        budget_tracker.stream_cost_charged += cost_usd

    return None


__all__ = ["charge_review_stream_step", "token_total_from_usage_payload"]