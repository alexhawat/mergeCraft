"""Streaming reviewer steps enforce the token ceiling before further spend."""

from __future__ import annotations

import pytest

from mergecraft.agents.shared import AgentUsage
from mergecraft.jev.cost import TokenBudget
from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker, RunBounds, record_agent_usage
from mergecraft.utils.stream_budget import charge_review_stream_step


def _bounds(*, token_budget: int = 2_000_000, tolerance: float = 0.1) -> RunBounds:
    return RunBounds(
        token_budget=token_budget,
        cost_budget_usd=10.0,
        tool_call_budget=100,
        run_timeout_s=60.0,
        context_retrieval_timeout_s=5.0,
        max_diff_lines=10_000,
        external_operation_timeout_s=30.0,
        token_budget_tolerance=tolerance,
    )


def test_single_increment_over_ceiling_raises_before_accepting() -> None:
    tracker = BudgetTracker(_bounds())
    ceiling = tracker.bounds.token_ceiling
    with pytest.raises(BudgetExhausted) as exc_info:
        tracker.record_tokens_stream_increment(ceiling + 1, phase="reviewer_dispatch")
    assert "single increment" in str(exc_info.value)
    assert tracker.tokens_used == 0


def test_stream_steps_stop_before_a_lump_finalize_increment() -> None:
    """Reproduce mycodefactory1 #50: one 3.38M lump must not be the only charge path."""
    tracker = BudgetTracker(_bounds())
    provider = TokenBudget(max_tokens=tracker.bounds.token_ceiling, advisory=False)
    payload = {"input_tokens": 1_800_000, "output_tokens": 50_000}
    assert charge_review_stream_step(payload, budget_tracker=tracker, provider_budget=provider) is None
    payload2 = {"input_tokens": 600_000, "output_tokens": 10_000}
    reason = charge_review_stream_step(payload2, budget_tracker=tracker, provider_budget=provider)
    assert reason is not None
    assert "single increment" in reason or "remaining ceiling" in reason


def test_finalize_records_only_usage_delta_after_stream_steps() -> None:
    tracker = BudgetTracker(_bounds())
    tracker.stream_tokens_charged = 150
    tracker.tokens_used = 150
    record_agent_usage(
        tracker,
        AgentUsage(agent="opencode", input_tokens=120, output_tokens=30),
        phase="reviewer_dispatch",
    )
    assert tracker.tokens_used == 150
    assert tracker.stream_tokens_charged == 150