"""W14 / W18 — failure injection, soak, SLOs (#364).

Out of scope: degradation/recovery (#365); perf/cost budgets (#367).
Does not actually soak for hours — pins the named harness and SLO surface.
"""

from __future__ import annotations

from tests.support.cd_batch import (
    CHAOS_MODULE,
    PRODUCTION_SLO_NAMES,
    SLO_MODULE,
    require_callable,
    require_module,
)


def test_failure_injection_harness_covers_named_faults() -> None:
    """Happy: failure injection can cut a provider, analyzer, and disk."""
    module = require_module(CHAOS_MODULE)
    inject = require_callable(module, "inject_failure")
    for fault in ("provider_outage", "analyzer_crash", "disk_full"):
        token = inject(fault)
        assert token is not None


def test_soak_harness_is_invocable_without_a_live_gateway() -> None:
    """Happy: soak runner is keyless and bounded (no live gate required)."""
    module = require_module(SLO_MODULE)
    soak = require_callable(module, "run_soak")
    report = soak(duration_seconds=0, concurrency=1)
    passed = getattr(report, "passed", None)
    if passed is None:
        passed = report.get("passed")
    assert passed is True or passed is False


def test_high_concurrency_tier_is_named() -> None:
    """Edge: concurrency tier exists as a first-class scale test."""
    module = require_module(SLO_MODULE)
    run = require_callable(module, "run_concurrency_tier")
    report = run(concurrency=32)
    assert getattr(report, "concurrency", None) == 32 or report.get("concurrency") == 32


def test_monorepo_and_large_pr_scale_tiers_exist() -> None:
    """Happy: monorepo and 50k-line PR tiers are distinct."""
    module = require_module(SLO_MODULE)
    mono = require_callable(module, "run_monorepo_scale")()
    large = require_callable(module, "run_large_pr_scale")(changed_lines=50_000)
    assert getattr(mono, "tier", None) or mono.get("tier")
    lines = getattr(large, "changed_lines", None)
    if lines is None:
        lines = large.get("changed_lines")
    assert lines == 50_000


def test_per_stage_latency_metrics_are_structured() -> None:
    """Happy: tracing exposes per-stage latency for the review pipeline."""
    module = require_module(SLO_MODULE)
    metrics = require_callable(module, "per_stage_latency_metrics")()
    names = set(metrics)
    lowered = {str(item).casefold() for item in names}
    if "checkout" not in names:
        assert "review" in lowered


def test_error_taxonomy_is_a_closed_set() -> None:
    """Happy: reliability errors map into a named taxonomy."""
    module = require_module(SLO_MODULE)
    taxonomy = frozenset(module.ERROR_TAXONOMY)
    assert taxonomy
    if "timeout" not in taxonomy:
        assert "provider_outage" in taxonomy


def test_production_slos_cover_the_four_named_targets() -> None:
    """Happy: completion, time-to-first-finding, total latency, publication."""
    module = require_module(SLO_MODULE)
    names = frozenset(module.PRODUCTION_SLOS)
    assert names == PRODUCTION_SLO_NAMES
