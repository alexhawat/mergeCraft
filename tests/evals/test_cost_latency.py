"""EV2 — cost/latency reporting: p50 and p95.

RED suite for PR EV2 (sub-wave EV2.1; implementation EV2.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

A benchmark run's latency story is its tail, not its mean — so the published
result set reports percentiles (plan §EV2.1: ``test_p50_and_p95_reported``).
The pinned contract lives in ``evals/benchmark.py`` (the result-set side —
global convention 7: production emits per-case durations, scoring folds them
here):

- ``LatencySummary`` (new model): ``p50_ms: float`` and ``p95_ms: float``.
- ``summarize_latencies(durations_ms: list[float]) -> LatencySummary``.
- Percentile method is pinned so two implementations cannot disagree: **linear
  interpolation between closest ranks over the sorted sample** (the numpy
  default). The worked example below is hand-computed against that rule.

Both symbols are imported lazily inside the test (ImportError at RED time;
collection stays clean). Keyless and pure: ``skipped: no live gate``.
"""

from __future__ import annotations

import pytest

_XFAIL_EV2_2 = pytest.mark.xfail(
    reason="green after EV2.2: LatencySummary + summarize_latencies (p50/p95)",
    strict=False,
)


@_XFAIL_EV2_2
def test_p50_and_p95_reported() -> None:
    """20 durations, 10..200ms in 10ms steps. Linear interpolation between
    closest ranks: p50 sits at rank 9.5 -> (100 + 110) / 2 = 105.0; p95 at
    rank 18.05 -> 190 + 0.05 * (200 - 190) = 190.5."""
    from mergecraft.evals.benchmark import summarize_latencies

    summary = summarize_latencies([float(10 * i) for i in range(1, 21)])

    assert summary.p50_ms == pytest.approx(105.0)
    assert summary.p95_ms == pytest.approx(190.5)
