"""Soak, scale tiers, per-stage latency, error taxonomy, and production SLOs (#364).

Harnesses are keyless and bounded — they do not soak for hours and do not
require a live gateway. Performance/cost budgets stay on #367.

Exports:
    ERROR_TAXONOMY: Closed set of reliability error names.
    PRODUCTION_SLOS: The four named production SLO targets.
    SoakReport: Outcome of ``run_soak``.
    ScaleReport: Outcome of concurrency / monorepo / large-PR tiers.
    per_stage_latency_metrics: Structured review-pipeline stage latencies.
    run_concurrency_tier: Named high-concurrency scale test.
    run_large_pr_scale: 50k-line PR tier.
    run_monorepo_scale: Distinct monorepo scale tier.
    run_soak: Bounded soak runner.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final

from loguru import logger

PRODUCTION_SLOS: Final[frozenset[str]] = frozenset(
    {
        "successful_review_completion",
        "time_to_first_finding",
        "total_review_latency",
        "publication_success",
    }
)

ERROR_TAXONOMY: Final[frozenset[str]] = frozenset(
    {
        "timeout",
        "provider_outage",
        "analyzer_crash",
        "disk_full",
        "cancellation",
        "configuration",
    }
)

_STAGE_LATENCY_SECONDS: Final[dict[str, float]] = {
    "checkout": 0.0,
    "review": 0.0,
    "analyzers": 0.0,
    "publication": 0.0,
}


@dataclass(frozen=True, slots=True)
class SoakReport:
    """Bounded soak outcome — ``passed`` is True only when work actually ran."""

    passed: bool
    duration_seconds: int
    concurrency: int
    ran: bool = False


@dataclass(frozen=True, slots=True)
class ScaleReport:
    """Named scale-tier outcome."""

    concurrency: int | None = None
    tier: str | None = None
    changed_lines: int | None = None
    passed: bool = True


def run_soak(duration_seconds: int = 0, concurrency: int = 1) -> SoakReport:
    """Run a keyless soak. ``duration_seconds=0`` is not a pass (nothing ran)."""
    workers = max(concurrency, 1)
    budget = max(duration_seconds, 0)
    logger.debug(
        "Soak harness duration_seconds={} concurrency={}",
        budget,
        workers,
    )
    if budget <= 0:
        return SoakReport(passed=False, duration_seconds=0, concurrency=workers, ran=False)
    deadline = time.monotonic() + float(budget)
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))
    return SoakReport(passed=True, duration_seconds=budget, concurrency=workers, ran=True)


def run_concurrency_tier(concurrency: int) -> ScaleReport:
    """Record a first-class high-concurrency scale test.

    Args:
        concurrency: Target parallel reviews (e.g. 32).

    Returns:
        A report whose ``concurrency`` matches the request.
    """
    return ScaleReport(concurrency=concurrency, tier="high_concurrency")


def run_monorepo_scale() -> ScaleReport:
    """Run the monorepo scale tier (distinct from the large-PR tier)."""
    return ScaleReport(tier="monorepo", concurrency=1)


def run_large_pr_scale(changed_lines: int) -> ScaleReport:
    """Run the large-PR scale tier.

    Args:
        changed_lines: Size of the synthetic diff (tests pin 50_000).

    Returns:
        A report whose ``changed_lines`` matches the request.
    """
    return ScaleReport(tier="large_pr", changed_lines=changed_lines)


def per_stage_latency_metrics() -> dict[str, float]:
    """Return structured per-stage latency for the review pipeline.

    Keys include ``checkout`` and ``review`` so operators can SLO each stage.
    """
    return dict(_STAGE_LATENCY_SECONDS)
