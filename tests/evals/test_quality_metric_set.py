"""W10.1 — quality metric set (#384).

Blocker precision, duplicate rate, and p50/p95 already exist on the eval
substrate. This module pins the *missing* metric set that turns that substrate
into a defensible quality claim.
Intended public API (W10.2): ``mergecraft.evals.quality_metrics``.
"""

from __future__ import annotations

import math

import pytest

_W102 = pytest.mark.xfail(
    reason="green after W10.2: eval quality metric set (#384)",
    strict=False,
)

_REQUIRED_FIELDS = (
    "blocker_precision",
    "severity_accuracy",
    "duplicate_rate",
    "unsupported_finding_rate",
    "contradiction_rate",
    "time_to_first_useful_finding_ms",
    "p50_ms",
    "p95_ms",
    "cost_per_review",
)


@_W102
def test_quality_metrics_expose_required_fields() -> None:
    """Happy: the metric set includes every #384 measurement."""
    from mergecraft.evals.quality_metrics import QualityMetrics, compute_quality_metrics

    metrics = compute_quality_metrics(
        findings=(),
        baseline=(),
        latencies_ms=(10.0, 20.0, 30.0),
        cost_usd=1.25,
        time_to_first_useful_finding_ms=15.0,
    )
    assert isinstance(metrics, QualityMetrics)
    for field_name in _REQUIRED_FIELDS:
        assert hasattr(metrics, field_name), f"QualityMetrics missing {field_name}"


@_W102
def test_quality_metrics_empty_findings_are_zero_not_nan() -> None:
    """Edge: empty findings yield 0.0 rates, never NaN (honest-zero, not fabricated recall)."""
    from mergecraft.evals.quality_metrics import compute_quality_metrics

    metrics = compute_quality_metrics(
        findings=(),
        baseline=(),
        latencies_ms=(1.0,),
        cost_usd=0.0,
        time_to_first_useful_finding_ms=None,
    )
    for field_name in (
        "duplicate_rate",
        "unsupported_finding_rate",
        "contradiction_rate",
    ):
        value = getattr(metrics, field_name)
        assert value == 0.0
        assert not math.isnan(value)


@_W102
def test_quality_metrics_reject_empty_latency_sample() -> None:
    """Error: a latency summary over nothing raises ValueError (never a fake 0.0)."""
    from mergecraft.evals.quality_metrics import compute_quality_metrics

    with pytest.raises(ValueError, match="latency"):
        compute_quality_metrics(
            findings=(),
            baseline=(),
            latencies_ms=(),
            cost_usd=0.0,
            time_to_first_useful_finding_ms=None,
        )


@_W102
def test_severity_accuracy_is_independent_of_blocker_precision() -> None:
    """Happy: severity accuracy can move independently of blocker precision."""
    from mergecraft.evals.quality_metrics import compute_quality_metrics

    from mergecraft.evals.scoring import BaselineIssue, ReportedFinding

    issues = [
        BaselineIssue(id="a", path="src/a.py", start_line=10, end_line=12, severity="Critical"),
    ]
    findings = [
        ReportedFinding(path="src/a.py", start_line=10, end_line=12, severity="Minor"),
    ]
    metrics = compute_quality_metrics(
        findings=findings,
        baseline=issues,
        latencies_ms=(5.0,),
        cost_usd=0.1,
        time_to_first_useful_finding_ms=5.0,
    )
    assert metrics.severity_accuracy < 1.0
    assert metrics.blocker_precision is not None
