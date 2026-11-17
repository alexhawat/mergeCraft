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


def test_samples_from_packets_reads_usage_and_wall_time() -> None:
    from mergecraft.review.budget_trend import samples_from_packets

    rows = samples_from_packets(
        [
            {
                "run_metrics": {
                    "phase_elapsed_s": {"review": 10.0, "setup": 2.5},
                    "recorded_cost_usd": 0.12,
                },
                "usage_entries": [{"input_tokens": 100, "output_tokens": 50}],
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0].tokens == 150
    assert rows[0].cost_usd == 0.12
    assert rows[0].wall_seconds == 12.5
