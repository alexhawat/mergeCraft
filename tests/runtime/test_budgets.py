"""CC3 — per-run budget enforcement (`.ignorelocal/02-cli-sources-trust-wave-plan.md`).

Authoring wave: **CC3.1** (RED). Implementation: **CC3.2**.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

_CC3_2_XFAIL = pytest.mark.xfail(
    reason="green after CC3.2: RunBounds budget enforcement",
    strict=False,
)


def _run_bounds() -> Any:
    try:
        return importlib.import_module("mergecraft.utils.run_bounds")
    except ImportError as exc:
        pytest.fail(f"mergecraft.utils.run_bounds not importable: {exc}")


def _outcome_mod() -> Any:
    return importlib.import_module("mergecraft.run_outcome")


def _tight_bounds() -> Any:
    mod = _run_bounds()
    RunBounds = mod.RunBounds
    return RunBounds(
        token_budget=100,
        cost_budget_usd=0.01,
        tool_call_budget=2,
        run_timeout_s=60.0,
        context_retrieval_timeout_s=5.0,
        max_diff_lines=10_000,
        external_operation_timeout_s=30.0,
    )


@_CC3_2_XFAIL
def test_token_budget_per_run_is_enforced() -> None:
    """Token usage beyond the resolved budget raises ``BudgetExhausted``."""
    mod = _run_bounds()
    tracker = mod.BudgetTracker(_tight_bounds())
    tracker.record_tokens(99)
    tracker.record_tokens(1)
    with pytest.raises(mod.BudgetExhausted) as exc_info:
        tracker.record_tokens(1)
    assert exc_info.value.kind == "token"


@_CC3_2_XFAIL
def test_cost_budget_per_run_is_enforced() -> None:
    """Cost usage beyond the resolved budget raises ``BudgetExhausted``."""
    mod = _run_bounds()
    tracker = mod.BudgetTracker(_tight_bounds())
    tracker.record_cost(0.009)
    tracker.record_cost(0.001)
    with pytest.raises(mod.BudgetExhausted) as exc_info:
        tracker.record_cost(0.0001)
    assert exc_info.value.kind == "cost"


@_CC3_2_XFAIL
def test_tool_call_budget_is_enforced() -> None:
    """Tool-call count beyond the resolved budget raises ``BudgetExhausted``."""
    mod = _run_bounds()
    tracker = mod.BudgetTracker(_tight_bounds())
    tracker.record_tool_call()
    tracker.record_tool_call()
    with pytest.raises(mod.BudgetExhausted) as exc_info:
        tracker.record_tool_call()
    assert exc_info.value.kind == "tool_call"


@_CC3_2_XFAIL
def test_budget_exhaustion_yields_inconclusive_not_a_partial_approval() -> None:
    """Budget exhaustion downgrades to ``inconclusive`` — never ``passed`` (D12)."""
    mod = _run_bounds()
    outcome_mod = _outcome_mod()
    bounds = mod.resolve_run_bounds(env={})
    outcome = mod.budget_exhaustion_outcome(mod.BudgetExhausted("token", "token budget exhausted"))
    assert outcome is outcome_mod.RunOutcome.inconclusive
    assert outcome is not outcome_mod.RunOutcome.passed
    assert bounds.token_budget is not None or bounds.tool_call_budget is not None
