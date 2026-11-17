"""Review budget target trend math (#1494)."""

from __future__ import annotations

import pytest

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


def test_target_warnings_cover_cost_and_wall_time() -> None:
    settings = ReviewBudgetSettings(
        target=ReviewBudgetTargetSettings(cost_usd_p50=0.01, wall_seconds_p50=30),
    )
    stats = {
        "cost_usd_p50": 0.05,
        "cost_usd_p90": 0.08,
        "wall_seconds_p50": 90.0,
        "wall_seconds_p90": 120.0,
    }
    warnings = target_warnings(settings, stats, window_n=3)
    metrics = {m for m, _ in warnings}
    assert metrics == {"cost_usd", "wall_seconds"}


@pytest.mark.asyncio
async def test_ensure_tracking_issue_creates_then_updates() -> None:
    from mergecraft.review.budget_trend import ensure_tracking_issue

    class _Scm:
        def __init__(self) -> None:
            self.created: list[dict] = []
            self.updated: list[int] = []

        async def list_issues(self, *args, **kwargs):
            del args, kwargs
            return []

        async def create_issue(self, *args, **kwargs):
            del args
            self.created.append(kwargs)

        async def update_issue(self, owner, repo, number, **kwargs):
            del owner, repo, kwargs
            self.updated.append(number)

    scm = _Scm()
    await ensure_tracking_issue(scm, "acme", "demo", metric="tokens", body="high tokens")
    assert len(scm.created) == 1

    async def _list_open(*args, **kwargs):
        del args, kwargs
        return [{"title": scm.created[0]["title"], "number": 42}]

    scm.list_issues = _list_open  # type: ignore[method-assign]
    await ensure_tracking_issue(scm, "acme", "demo", metric="tokens", body="still high")
    assert scm.updated == [42]


@pytest.mark.asyncio
async def test_emit_budget_trend_advisory_with_targets() -> None:
    from types import SimpleNamespace

    from mergecraft.config.settings import ReviewBudgetTargetSettings
    from mergecraft.review.budget_trend import emit_budget_trend_advisory

    packet = SimpleNamespace(
        model_dump=lambda: {
            "run_metrics": {"phase_elapsed_s": {"review": 100.0}, "recorded_cost_usd": 2.0},
            "usage_entries": [{"input_tokens": 500_000, "output_tokens": 50_000}],
        }
    )
    ctx = SimpleNamespace(
        settings=SimpleNamespace(
            review=SimpleNamespace(
                budget=ReviewBudgetSettings(
                    target=ReviewBudgetTargetSettings(tokens_p50=10_000),
                    window_size=5,
                )
            )
        ),
        tool_state=SimpleNamespace(prepared_run_packet=packet),
        tool_context=None,
    )
    await emit_budget_trend_advisory(ctx)
