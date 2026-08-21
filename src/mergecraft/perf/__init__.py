"""Latency/cost budgets, compression, early stop, and regression benches (#367).

Exports:
    ReviewContextCache: Repo map, symbols, analyzer results, immutable summaries.
    enforce_cost_ceiling: Fail closed when ensemble spend exceeds the profile.
    perf_metrics: Per-agent tokens and cache hit/miss counters.
    review_stage_order: Cheap classification before specialist fan-out.
"""

from __future__ import annotations

from mergecraft.perf.budgets import (
    ReviewContextCache,
    enforce_cost_ceiling,
    perf_metrics,
    review_stage_order,
)

__all__ = [
    "ReviewContextCache",
    "enforce_cost_ceiling",
    "perf_metrics",
    "review_stage_order",
]
