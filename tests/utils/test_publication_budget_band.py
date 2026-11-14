"""Token usage bands are advisory and preserve complete accounting."""

from __future__ import annotations

import inspect
from typing import Any

import pytest
from loguru import logger

from mergecraft.utils.run_bounds import BudgetExhausted, BudgetTracker, RunBounds


def _base_bounds(**overrides: Any) -> RunBounds:
    """Construct :class:`RunBounds` including W5 tolerance when present."""
    fields = RunBounds.__dataclass_fields__
    defaults: dict[str, Any] = {
        "token_budget": 100,
        "cost_budget_usd": 1.0,
        "tool_call_budget": 10,
        "run_timeout_s": 60.0,
        "context_retrieval_timeout_s": 5.0,
        "max_diff_lines": 10_000,
        "external_operation_timeout_s": 30.0,
    }
    if "token_budget_tolerance" in fields:
        defaults["token_budget_tolerance"] = 0.10
    defaults.update(overrides)
    return RunBounds(**defaults)


def test_crossing_target_under_ceiling_warns_once_without_raise() -> None:
    """D9 — 7% over target warns once and continues; no ``BudgetExhausted``."""
    bounds = _base_bounds(token_budget=100, token_budget_tolerance=0.10)
    tracker = BudgetTracker(bounds)
    warnings: list[str] = []
    handler_id = logger.add(lambda msg: warnings.append(msg.record["message"]), level="WARNING")
    try:
        tracker.record_tokens(70)
        tracker.record_tokens(37)  # 107 > 100 target, < 110 ceiling
        assert tracker.tokens_used == 107
    finally:
        logger.remove(handler_id)
    over_target = [
        line for line in warnings if "target" in line.lower() or "budget" in line.lower()
    ]
    assert len(over_target) == 1


def test_over_target_warning_emitted_only_once() -> None:
    """D9 — subsequent increments must not spam warnings."""
    bounds = _base_bounds(token_budget=100, token_budget_tolerance=0.10)
    tracker = BudgetTracker(bounds)
    warnings: list[str] = []
    handler_id = logger.add(lambda msg: warnings.append(msg.record["message"]), level="WARNING")
    try:
        tracker.record_tokens(101)
        tracker.record_tokens(1)
        tracker.record_tokens(1)
    finally:
        logger.remove(handler_id)
    over_target = [line for line in warnings if "target" in line.lower()]
    assert len(over_target) == 1


@pytest.mark.parametrize("tolerance", [0.0, 0.10])
@pytest.mark.parametrize("increments", [(111,), (100, 11), (95, 20)])
def test_token_overruns_record_full_usage_without_failing(
    tolerance: float, increments: tuple[int, ...]
) -> None:
    """Both aggregate and incremental overages remain advisory."""
    tracker = BudgetTracker(_base_bounds(token_budget_tolerance=tolerance))
    for count in increments:
        tracker.record_tokens(count, phase="reviewer_dispatch")
    assert tracker.tokens_used == sum(increments)
    assert tracker.phase_totals == {"reviewer_dispatch": sum(increments)}
    assert tracker.over_target is True
    assert tracker.last_exhausted is None


def test_record_tokens_without_phase_attributes_to_unattributed() -> None:
    """D11 — unannotated ``record_tokens`` calls attribute to ``unattributed``."""
    sig = inspect.signature(BudgetTracker.record_tokens)
    assert "phase" in sig.parameters
    tracker = BudgetTracker(_base_bounds())
    tracker.record_tokens(25)
    totals = getattr(tracker, "phase_totals", None)
    assert totals is not None
    assert totals.get("unattributed") == 25


def test_per_phase_totals_sum_to_tokens_used() -> None:
    """D11 — phase buckets reconcile to ``tokens_used``."""
    tracker = BudgetTracker(_base_bounds())
    tracker.record_tokens(10, phase="reviewer_dispatch")
    tracker.record_tokens(5)
    tracker.record_tokens(7, phase="analyzer_pipeline")
    totals = getattr(tracker, "phase_totals", {})
    assert sum(totals.values()) == tracker.tokens_used == 22


def test_record_cost_path_is_untouched_by_token_band_changes() -> None:
    """D11 — cost accounting must remain independent of the token band."""
    bounds = _base_bounds(cost_budget_usd=0.05)
    tracker = BudgetTracker(bounds)
    tracker.record_cost(0.04)
    with pytest.raises(BudgetExhausted) as exc_info:
        tracker.record_cost(0.02)
    assert exc_info.value.kind == "cost"
    assert tracker.cost_used == pytest.approx(0.06)
