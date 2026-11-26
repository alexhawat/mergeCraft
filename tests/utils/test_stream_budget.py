"""Streaming reviewer steps enforce the token ceiling before further spend."""

from __future__ import annotations

import pytest

from mergecraft.agents.shared import AgentUsage
from mergecraft.agents.stream_budget import charge_review_stream_step
from mergecraft.jev.cost import TokenBudget
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    BudgetTracker,
    RunBounds,
    StreamCharges,
    record_agent_usage,
)


def _bounds(
    *,
    token_budget: int = 2_000_000,
    tolerance: float = 0.1,
    cost_budget_usd: float = 10.0,
) -> RunBounds:
    return RunBounds(
        token_budget=token_budget,
        cost_budget_usd=cost_budget_usd,
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
    assert (
        charge_review_stream_step(
            payload, budget_tracker=tracker, provider_budget=provider, stream_charges=None
        )
        is None
    )
    payload2 = {"input_tokens": 600_000, "output_tokens": 10_000}
    reason = charge_review_stream_step(
        payload2, budget_tracker=tracker, provider_budget=provider, stream_charges=None
    )
    assert reason is not None
    assert "single increment" in reason or "remaining ceiling" in reason


def test_charge_stops_on_cost_budget() -> None:
    bounds = _bounds(cost_budget_usd=0.01)
    tracker = BudgetTracker(bounds)
    reason = charge_review_stream_step(
        {"input_tokens": 1, "output_tokens": 0},
        budget_tracker=tracker,
        provider_budget=None,
        stream_charges=None,
        cost_usd=0.02,
    )
    assert reason is not None
    assert "cost budget" in reason.lower()


def test_consume_stream_stops_when_handler_sets_halt_reason() -> None:
    from mergecraft.agents._stream_consumer import StreamSpanAccumulator, consume_stream

    accumulator = StreamSpanAccumulator(agent_name="test")
    lines = [
        '{"type": "step_finish", "part": {"tokens": {"input": 1, "output": 0}}}\n',
        '{"type": "step_finish", "part": {"tokens": {"input": 2, "output": 0}}}\n',
    ]

    def handler(acc: StreamSpanAccumulator, _event: dict) -> None:
        acc.halt_reason = "budget"

    consume_stream(raw_stream=lines, accumulator=accumulator, handler=handler)
    assert accumulator.parsed_event_count == 1
    assert accumulator.halt_reason == "budget"


def test_finalize_records_only_usage_delta_after_stream_steps() -> None:
    tracker = BudgetTracker(_bounds())
    charges = StreamCharges()
    reason = charge_review_stream_step(
        {"input_tokens": 100, "output_tokens": 20},
        budget_tracker=tracker,
        provider_budget=None,
        stream_charges=charges,
        cost_usd=0.2,
    )
    assert reason is None
    assert charges == StreamCharges(tokens=120, cost_usd=0.2, input_tokens=100, output_tokens=20)

    record_agent_usage(
        tracker,
        AgentUsage(agent="opencode", input_tokens=120, output_tokens=30, cost_usd=0.25),
        phase="reviewer_dispatch",
        streamed=charges,
    )

    assert tracker.tokens_used == 150
    assert tracker.cost_used == pytest.approx(0.25)


def test_usage_below_the_streamed_total_charges_nothing_more() -> None:
    """A halted step is charged before it is absorbed, so usage can be the smaller total."""
    tracker = BudgetTracker(_bounds(), tokens_used=150, cost_used=0.3)
    record_agent_usage(
        tracker,
        AgentUsage(agent="opencode", input_tokens=100, output_tokens=20, cost_usd=0.2),
        streamed=StreamCharges(tokens=150, cost_usd=0.3),
    )
    assert tracker.tokens_used == 150
    assert tracker.cost_used == pytest.approx(0.3)


# --------------------------------------------------------------------------- crossing step (#1587)


def _ceiling_bounds() -> RunBounds:
    return _bounds(token_budget=100, tolerance=0.0, cost_budget_usd=1.0)


@pytest.mark.parametrize(
    ("steps", "stops_at"),
    [
        pytest.param([(65, 0.01), (55, 0.02)], 1, id="second-step-crosses"),
        pytest.param([(120, 0.03)], 0, id="first-step-crosses"),
        pytest.param([(65, 0.01), (35, 0.02)], None, id="exactly-the-ceiling"),
    ],
)
def test_a_completed_step_is_charged_even_when_it_crosses_the_ceiling(
    steps: list[tuple[int, float]], stops_at: int | None
) -> None:
    """The step already ran: its tokens and cost count once; only the decision is a stop."""
    tracker = BudgetTracker(_ceiling_bounds())
    charges = StreamCharges()
    reasons = [
        charge_review_stream_step(
            {"input_tokens": tokens, "output_tokens": 0},
            budget_tracker=tracker,
            provider_budget=None,
            stream_charges=charges,
            cost_usd=cost,
        )
        for tokens, cost in steps
    ]

    tokens = sum(step_tokens for step_tokens, _cost in steps)
    cost = sum(step_cost for _tokens, step_cost in steps)
    # Only the crossing step returns a stop reason, and it names the token budget.
    assert [reason is not None for reason in reasons] == [
        index == stops_at for index in range(len(steps))
    ]
    assert all("token budget" in reason for reason in reasons if reason is not None)
    assert (tracker.last_exhausted is not None) is (stops_at is not None)
    assert tracker.tokens_used == tokens
    assert tracker.cost_used == pytest.approx(cost)
    assert (charges.tokens, charges.input_tokens, charges.output_tokens) == (tokens, tokens, 0)
    assert charges.cost_usd == pytest.approx(cost)

    # Aggregate reconciliation adds nothing the stream already charged.
    record_agent_usage(
        tracker,
        AgentUsage(agent="opencode", input_tokens=tokens, output_tokens=0, cost_usd=cost),
        streamed=charges,
    )
    assert tracker.tokens_used == tokens
    assert tracker.cost_used == pytest.approx(cost)


def test_a_step_that_crosses_the_cost_ceiling_is_charged_once() -> None:
    """``record_cost`` adds before it raises, so the stream must count that cost as charged."""
    tracker = BudgetTracker(_bounds(cost_budget_usd=0.01))
    charges = StreamCharges()

    reason = charge_review_stream_step(
        {"input_tokens": 10, "output_tokens": 0},
        budget_tracker=tracker,
        provider_budget=None,
        stream_charges=charges,
        cost_usd=0.02,
    )
    assert reason is not None
    assert "cost budget" in reason
    assert charges.cost_usd == pytest.approx(0.02)

    with pytest.raises(BudgetExhausted):
        record_agent_usage(
            tracker,
            AgentUsage(agent="opencode", input_tokens=10, output_tokens=0, cost_usd=0.03),
            streamed=charges,
        )
    # Only the 0.01 the stream never saw is added on top of the streamed 0.02.
    assert tracker.cost_used == pytest.approx(0.03)


def test_a_provider_budget_stop_still_charges_the_step_cost() -> None:
    tracker = BudgetTracker(_bounds())
    provider = TokenBudget(max_tokens=50, advisory=False)
    charges = StreamCharges()

    reason = charge_review_stream_step(
        {"input_tokens": 60, "output_tokens": 0},
        budget_tracker=tracker,
        provider_budget=provider,
        stream_charges=charges,
        cost_usd=0.4,
    )

    assert reason == "budget"
    assert tracker.cost_used == pytest.approx(0.4)
    assert charges == StreamCharges(tokens=60, cost_usd=0.4, input_tokens=60)
