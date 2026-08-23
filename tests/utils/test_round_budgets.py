"""Round-aware budgets (RC12) — W9.1 RED suite.

Wave plan: ``.ignorelocal/waves/review-convergence-wave-plan.md`` (W9).
Pins ``review.roundBudgets``, round-scaled ``resolve_run_bounds``, and
``effective_agent_limits``. Implementation lands in W9.2.
"""

from __future__ import annotations

import inspect
from itertools import pairwise
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.run_bounds import (
    BudgetExhausted,
    BudgetTracker,
    budget_exhaustion_outcome,
    resolve_run_bounds,
)

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings

_TAPER_MULTIPLIERS: tuple[float, float, float, float] = (1.5, 1.0, 0.75, 0.5)
_BASELINE_TOKEN_BUDGET = 2_000_000
_BASELINE_TOOL_CALL_BUDGET = 500
_BASELINE_COST_BUDGET_USD = 50.0
_BASELINE_SUBAGENT_BUDGET = 8


def _tapered_settings() -> RepoSettings:
    """Build settings with explicit round multipliers once W9.2 adds the field."""
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    review_model = type(settings.review)
    review_fields = review_model.model_fields
    assert "round_budgets" in review_fields, "W9.2: review.roundBudgets on ReviewSettings"
    field = review_fields["round_budgets"]
    round_budgets = field.annotation(
        multipliers=list(_TAPER_MULTIPLIERS),
    )
    review = settings.review.model_copy(update={"round_budgets": round_budgets})
    return settings.model_copy(update={"review": review})


def _resolve_bounds_for_round(settings: RepoSettings, round_index: int) -> Any:
    """Resolve run bounds for a review round (W9.2 ``round_index`` parameter)."""
    sig = inspect.signature(resolve_run_bounds)
    assert "round_index" in sig.parameters, "W9.2: resolve_run_bounds(round_index=…)"
    return resolve_run_bounds(settings=settings, round_index=round_index)


def _effective_limits_for_round(
    binding: Any,
    *,
    settings: RepoSettings,
    round_index: int,
) -> Any:
    """Resolve subagent limits for a review round (W9.2 round-aware limits)."""
    from mergecraft.agents.registry import effective_agent_limits

    sig = inspect.signature(effective_agent_limits)
    assert "round_index" in sig.parameters, "W9.2: effective_agent_limits(round_index=…)"
    return effective_agent_limits(binding, settings=settings, round_index=round_index)


def test_first_review_gets_the_deep_allocation() -> None:
    """Round 1 receives a larger token and tool-call budget than round 2 (RC12)."""
    settings = _tapered_settings()
    round_one = _resolve_bounds_for_round(settings, round_index=1)
    round_two = _resolve_bounds_for_round(settings, round_index=2)

    assert round_one.token_budget > round_two.token_budget
    assert round_one.tool_call_budget > round_two.tool_call_budget
    assert round_one.token_budget == int(_BASELINE_TOKEN_BUDGET * _TAPER_MULTIPLIERS[0])
    assert round_two.token_budget == int(_BASELINE_TOKEN_BUDGET * _TAPER_MULTIPLIERS[1])


def test_incremental_rounds_taper() -> None:
    """Later review rounds monotonically taper run budgets (RC12)."""
    settings = _tapered_settings()
    bounds = [_resolve_bounds_for_round(settings, round_index=index) for index in (1, 2, 3, 4)]

    for earlier, later in pairwise(bounds):
        assert earlier.token_budget >= later.token_budget
        assert earlier.tool_call_budget >= later.tool_call_budget
        assert earlier.cost_budget_usd >= later.cost_budget_usd

    assert bounds[0].token_budget > bounds[1].token_budget
    assert bounds[1].token_budget > bounds[2].token_budget


def test_round_budgets_default_preserves_current_totals() -> None:
    """Default config keeps today's flat totals — no opt-in regression (D1 invariant)."""
    from mergecraft.agents.registry import (
        _DEFAULT_BUDGET,
        AgentRole,
        effective_agent_limits,
        load_registry,
    )
    from mergecraft.config.settings import default_settings

    settings = default_settings()
    flat_bounds = resolve_run_bounds(settings=settings)

    assert flat_bounds.token_budget == _BASELINE_TOKEN_BUDGET
    assert flat_bounds.tool_call_budget == _BASELINE_TOOL_CALL_BUDGET
    assert flat_bounds.cost_budget_usd == _BASELINE_COST_BUDGET_USD

    registry = load_registry(settings=settings)
    for role in (AgentRole.reviewer, AgentRole.verifier, AgentRole.recall):
        limits = effective_agent_limits(registry.resolve_role(role), settings=settings)
        assert limits.budget == _DEFAULT_BUDGET
        assert limits.budget == _BASELINE_SUBAGENT_BUDGET

    round_budgets = getattr(settings.review, "round_budgets", None)
    if round_budgets is not None:
        multipliers = getattr(round_budgets, "multipliers", None)
        if multipliers is not None:
            assert all(multiplier == 1.0 for multiplier in multipliers)

    sig = inspect.signature(resolve_run_bounds)
    if "round_index" in sig.parameters:
        round_one = resolve_run_bounds(settings=settings, round_index=1)
        round_three = resolve_run_bounds(settings=settings, round_index=3)
        assert round_one == flat_bounds
        assert round_three == flat_bounds


def test_budget_exhaustion_is_still_inconclusive_never_partial_approval() -> None:
    """Preserves ``budget_exhaustion_outcome`` at ``run_bounds.py:232-235`` (D12)."""
    for kind in ("token", "cost", "tool_call"):
        exc = BudgetExhausted(kind, f"{kind} budget exhausted")
        outcome = budget_exhaustion_outcome(exc)
        assert outcome is RunOutcome.inconclusive
        assert outcome is not RunOutcome.passed

    tracker = BudgetTracker(
        resolve_run_bounds(
            env={
                "MERGECRAFT_TOKEN_BUDGET": "10",
                "MERGECRAFT_TOOL_CALL_BUDGET": "1",
            },
        ),
    )
    tracker.record_tool_call()
    with pytest.raises(BudgetExhausted):
        tracker.record_tool_call()
    assert tracker.last_exhausted is not None
    assert budget_exhaustion_outcome(tracker.last_exhausted) is RunOutcome.inconclusive


def test_subagent_budget_scales_with_the_round() -> None:
    """Subagent ``budget`` follows the round multiplier via ``effective_agent_limits``."""
    from mergecraft.agents.registry import AgentRole, load_registry

    settings = _tapered_settings()
    registry = load_registry(settings=settings)
    binding = registry.resolve_role(AgentRole.verifier)

    round_one = _effective_limits_for_round(binding, settings=settings, round_index=1)
    round_three = _effective_limits_for_round(binding, settings=settings, round_index=3)

    assert round_one.budget > round_three.budget
    assert round_one.budget == int(_BASELINE_SUBAGENT_BUDGET * _TAPER_MULTIPLIERS[0])
    assert round_three.budget == int(_BASELINE_SUBAGENT_BUDGET * _TAPER_MULTIPLIERS[2])
