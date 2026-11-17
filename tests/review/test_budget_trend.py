"""Review budget target trend math (#1494)."""

from __future__ import annotations

from mergecraft.config.settings import ReviewBudgetSettings, ReviewBudgetTargetSettings
from mergecraft.review.budget_trend import (
    RunUsageSample,
    percentile,
    target_warnings,
    window_stats,
)


def test_percentile_with_fewer_than_window_runs() -> None:
    assert percentile([1.0, 3.0, 5.0], 0.5) == 3.0
    assert percentile([], 0.5) is None


def test_target_warning_when_p50_exceeds_target() -> None:
    settings = ReviewBudgetSettings(
        target=ReviewBudgetTargetSettings(tokens_p50=100_000),
    )
    stats = window_stats(
        [RunUsageSample(tokens=150_000, cost_usd=None, wall_seconds=None) for _ in range(5)]
    )
    warnings = target_warnings(settings, stats, window_n=5)
    assert warnings
    assert warnings[0][0] == "tokens"


def test_no_target_means_no_warnings() -> None:
    settings = ReviewBudgetSettings()
    stats = window_stats([RunUsageSample(tokens=999, cost_usd=9.0, wall_seconds=60.0)])
    assert target_warnings(settings, stats, window_n=1) == []
