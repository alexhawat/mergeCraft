"""CC3 — per-run budget enforcement (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC3.1** (RED). Implementation: **CC3.2**.
"""

from __future__ import annotations

import pytest

from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    BudgetTracker,
    RunBounds,
    budget_exhaustion_outcome,
    record_agent_usage,
    resolve_run_bounds,
)


def _tight_bounds() -> RunBounds:
    return RunBounds(
        token_budget=100,
        cost_budget_usd=0.01,
        tool_call_budget=2,
        run_timeout_s=60.0,
        context_retrieval_timeout_s=5.0,
        max_diff_lines=10_000,
        external_operation_timeout_s=30.0,
    )


def test_token_budget_per_run_is_enforced() -> None:
    """Token usage beyond the resolved budget raises ``BudgetExhausted``."""
    tracker = BudgetTracker(_tight_bounds())
    tracker.record_tokens(99)
    tracker.record_tokens(1)
    with pytest.raises(BudgetExhausted) as exc_info:
        tracker.record_tokens(1)
    assert exc_info.value.kind == "token"


def test_cost_budget_per_run_is_enforced() -> None:
    """Cost usage beyond the resolved budget raises ``BudgetExhausted``."""
    tracker = BudgetTracker(_tight_bounds())
    tracker.record_cost(0.009)
    tracker.record_cost(0.001)
    with pytest.raises(BudgetExhausted) as exc_info:
        tracker.record_cost(0.0001)
    assert exc_info.value.kind == "cost"


def test_tool_call_budget_is_enforced() -> None:
    """Tool-call count beyond the resolved budget raises ``BudgetExhausted``."""
    tracker = BudgetTracker(_tight_bounds())
    tracker.record_tool_call()
    tracker.record_tool_call()
    with pytest.raises(BudgetExhausted) as exc_info:
        tracker.record_tool_call()
    assert exc_info.value.kind == "tool_call"


def test_budget_exhaustion_yields_inconclusive_not_a_partial_approval() -> None:
    """Budget exhaustion downgrades to ``inconclusive`` — never ``passed`` (D12)."""
    bounds = resolve_run_bounds(env={})
    outcome = budget_exhaustion_outcome(BudgetExhausted("token", "token budget exhausted"))
    assert outcome is RunOutcome.inconclusive
    assert outcome is not RunOutcome.passed
    assert bounds.token_budget is not None or bounds.tool_call_budget is not None


def test_record_agent_usage_charges_token_and_cost_budgets() -> None:
    """Agent usage is charged against the per-run budget tracker."""
    from mergecraft.agents.shared import AgentUsage

    tracker = BudgetTracker(_tight_bounds())
    record_agent_usage(
        tracker,
        AgentUsage(agent="test", input_tokens=50, output_tokens=49, cost_usd=0.005),
    )
    with pytest.raises(BudgetExhausted) as exc_info:
        record_agent_usage(
            tracker,
            AgentUsage(agent="test", input_tokens=2, output_tokens=0, cost_usd=0.0),
        )
    assert exc_info.value.kind == "token"


def test_record_agent_usage_does_not_double_count_cached_input() -> None:
    """OpenAI-style cached input is already in ``input_tokens`` (D16 / #273)."""
    from mergecraft.agents.shared import AgentUsage

    tracker = BudgetTracker(_tight_bounds())
    record_agent_usage(
        tracker,
        AgentUsage(
            agent="test",
            input_tokens=90,
            output_tokens=5,
            cache_read_tokens=40,
        ),
    )
    assert tracker.tokens_used == 95
    with pytest.raises(BudgetExhausted) as exc_info:
        record_agent_usage(
            tracker,
            AgentUsage(agent="test", input_tokens=6, output_tokens=0, cache_read_tokens=40),
        )
    assert exc_info.value.kind == "token"


def test_tracker_records_last_exhausted_for_orchestrator_drain() -> None:
    """``BudgetTracker`` records the ``BudgetExhausted`` it raises.

    mergeCraft review (PR #242, finding ``aeb5d964c1d35e5a41784ded``) found
    the MCP ``tools/call`` handler only surfaces tool-call budget exhaustion
    as a JSON-RPC error — the orchestrator's ``_finalize`` only reads
    ``RunContext.budget_exhaustion``, populated from token/cost usage via
    ``record_agent_usage``. A run that exhausts its tool-call budget can
    therefore submit a terminal verdict and be approved.

    The fix records the exception on the tracker itself (``last_exhausted``),
    so a downstream orchestrator that drains the tracker at finalize time —
    regardless of which call site tripped the budget — sees the exhaustion
    and applies ``budget_exhaustion_outcome`` (D12).
    """
    tracker = BudgetTracker(_tight_bounds())
    tracker.record_tool_call()
    tracker.record_tool_call()
    assert tracker.last_exhausted is None
    with pytest.raises(BudgetExhausted):
        tracker.record_tool_call()
    assert isinstance(tracker.last_exhausted, BudgetExhausted)
    assert tracker.last_exhausted.kind == "tool_call"
    # Draining the tracker surfaces the same outcome mapping the orchestrator
    # would apply (D12 — inconclusive never a partial approval).
    assert budget_exhaustion_outcome(tracker.last_exhausted) is RunOutcome.inconclusive
