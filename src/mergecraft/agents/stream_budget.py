"""Per-step token charging for streaming reviewer drivers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.agents.shared import AgentUsage
    from mergecraft.jev.cost import TokenBudget
    from mergecraft.utils.run_bounds import StreamCharges

_PHASE = "reviewer_dispatch"


def _usage_from_payload(payload: Mapping[str, Any]) -> AgentUsage | None:
    """Return one usage payload as ``AgentUsage``, folded by the stream accumulator's rules."""
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator

    accumulator = StreamSpanAccumulator(agent_name="budget")
    accumulator.absorb_usage(payload)
    return accumulator.to_usage()


def token_total_from_usage_payload(payload: Mapping[str, Any]) -> int:
    """Return billed tokens for one usage payload using ``AgentUsage`` rules."""
    usage = _usage_from_payload(payload)
    if usage is None:
        return 0
    return usage.input_tokens + usage.output_tokens


def _note_observed_split(stream_charges: StreamCharges | None, usage: AgentUsage | None) -> None:
    """Keep the step's input/output split, so an abnormal end can still report it (#1588)."""
    if stream_charges is None or usage is None:
        return
    stream_charges.input_tokens += usage.input_tokens
    stream_charges.output_tokens += usage.output_tokens
    stream_charges.cache_read_tokens += usage.cache_read_tokens or 0
    stream_charges.cache_write_tokens += usage.cache_write_tokens or 0


def charge_review_stream_step(
    payload: Mapping[str, Any],
    *,
    budget_tracker: BudgetTracker | None,
    provider_budget: TokenBudget | None,
    stream_charges: StreamCharges | None,
    cost_usd: float | None = None,
) -> str | None:
    """Charge one completed stream step against run bounds; return a stop reason when over.

    A step's usage arrives after the provider already did the work, so the step
    is always accounted for, including the one that crosses a ceiling: its
    tokens are recorded on the advisory path and its cost is charged once. Only
    the decision changes — a reason is returned so the driver stops before any
    further spend (#1587).

    ``stream_charges`` collects what this dispatch charged to ``budget_tracker``,
    so its final usage charge adds only the remainder, plus the step's
    input/output split for a dispatch that ends before its final usage arrives.

    Returns:
        ``None`` when the step was within bounds. A human-readable reason when
        the run must stop before spending further provider tokens.
    """
    usage = _usage_from_payload(payload)
    count = usage.input_tokens + usage.output_tokens if usage is not None else 0
    if count <= 0 and (cost_usd is None or cost_usd <= 0):
        return None

    _note_observed_split(stream_charges, usage)
    stop: str | None = None
    if budget_tracker is not None and count > 0:
        try:
            budget_tracker.record_tokens_stream_increment(count, phase=_PHASE)
        except BudgetExhausted as exc:
            # The exhaustion stays on the tracker; the completed step's tokens are
            # still the run's, so they are recorded rather than dropped.
            budget_tracker.record_tokens(count, phase=_PHASE)
            stop = str(exc)
        if stream_charges is not None:
            stream_charges.tokens += count

    if provider_budget is not None and count > 0:
        from mergecraft.agents.token_budget import record_provider_usage

        if not record_provider_usage(
            provider_budget,
            input_tokens=count,
            output_tokens=0,
        ):
            stop = stop or provider_budget.stop_reason or "budget"

    if budget_tracker is not None and cost_usd is not None and cost_usd > 0:
        try:
            budget_tracker.record_cost(cost_usd)
        except BudgetExhausted as exc:
            stop = stop or str(exc)
        finally:
            # ``record_cost`` adds the amount before it raises, so the stream has
            # charged it either way; the final charge must not add it again.
            if stream_charges is not None:
                stream_charges.cost_usd += cost_usd

    return stop


__all__ = ["charge_review_stream_step", "token_total_from_usage_payload"]
