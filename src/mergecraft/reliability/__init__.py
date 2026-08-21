"""Soak, SLO, chaos, recovery, and redacted diagnostic-bundle surfaces (#364/#365).

Exports:
    ERROR_TAXONOMY: Closed reliability error names.
    PRODUCTION_SLOS: Named production SLO targets.
    inject_failure: Named fault injection (provider, analyzer, disk).
    on_provider_outage: Degrade instead of crashing mid-review.
    per_stage_latency_metrics: Structured review-pipeline stage latencies.
    recover_corrupt_cache: Rebuild a corrupt local cache.
    run_soak: Keyless, bounded soak harness.
    write_diagnostic_bundle: Operator bundle with secrets redacted.
"""

from __future__ import annotations

from mergecraft.reliability.chaos import inject_failure
from mergecraft.reliability.diagnostic_bundle import write_diagnostic_bundle
from mergecraft.reliability.recovery import on_provider_outage, recover_corrupt_cache
from mergecraft.reliability.slo import (
    ERROR_TAXONOMY,
    PRODUCTION_SLOS,
    per_stage_latency_metrics,
    run_soak,
)

__all__ = [
    "ERROR_TAXONOMY",
    "PRODUCTION_SLOS",
    "inject_failure",
    "on_provider_outage",
    "per_stage_latency_metrics",
    "recover_corrupt_cache",
    "run_soak",
    "write_diagnostic_bundle",
]
