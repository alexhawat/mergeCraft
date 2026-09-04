"""W8 / W10 — materiality, calibrated confidence, dismissal reason codes (#355).

Does not re-test dedup / causality / severity rubric (issue out of scope).
Does not turn dismissal into durable memory (that is #360 / W13).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.findings.support import make_finding
from tests.support.cc_batch import load_module, require_callable
from tests.support.dead_package_wiring import SRC_ROOT


def test_dedup_and_causality_modules_remain_the_shipped_precision_half() -> None:
    """#355 out of scope — do not rebuild dedup / causality (current state)."""
    assert (SRC_ROOT / "findings" / "dedup.py").is_file()
    assert (SRC_ROOT / "findings" / "causality.py").is_file()
    assert (SRC_ROOT / "findings" / "severity_rubric.py").is_file()


def test_materiality_scoring_ranks_security_above_style() -> None:
    """#354/#355 — materiality scoring; high-impact outranks style commentary."""
    module = load_module("mergecraft.findings.materiality")
    score = require_callable(module, "score_materiality")
    prioritize = require_callable(module, "prioritize_findings")
    security = make_finding(
        category="Security & Privacy",
        severity="Major",
        message="token logged",
        fingerprint="sec",
    )
    style = make_finding(
        category="Maintainability & Code Quality",
        severity="Minor",
        message="rename local",
        fingerprint="style",
    )
    assert score(security) > score(style)
    ordered = prioritize([style, security])
    assert ordered[0].fingerprint == security.fingerprint


def test_confidence_is_calibrated_from_benchmark_outcomes() -> None:
    """#355 — confidence comes from benchmark outcomes, not model self-report."""
    module = load_module("mergecraft.findings.materiality")
    calibrate = require_callable(module, "calibrate_confidence")
    finding = make_finding(confidence="certain", fingerprint="raw")
    calibrated = calibrate(finding, benchmark_hit_rate=0.4)
    value = getattr(calibrated, "confidence", calibrated)
    assert str(value) != "certain"


def test_finding_budgets_cover_severity_category_file_and_review() -> None:
    """#355 — budgets exist by severity, category, file, and review (not only inline)."""
    module = load_module("mergecraft.findings.materiality")
    apply_budgets = require_callable(module, "apply_finding_budgets")
    findings = [
        make_finding(
            severity="Minor", category="Maintainability & Code Quality", fingerprint=f"n{i}"
        )
        for i in range(12)
    ]
    kept = apply_budgets(
        findings,
        severity_budget=2,
        category_budget=3,
        file_budget=2,
        review_budget=4,
    )
    assert len(kept) <= 4


def test_publication_and_blocking_thresholds_are_configurable() -> None:
    """#355 — configurable publication minimums and stronger blocking thresholds."""
    module = load_module("mergecraft.findings.materiality")
    publishable = require_callable(module, "meets_publication_threshold")
    blocking = require_callable(module, "meets_blocking_threshold")
    major = make_finding(severity="Major", confidence="possible", fingerprint="maj")
    assert publishable(major, minimum={"severity": "Minor", "confidence": "possible"}) is True
    assert blocking(major, minimum={"severity": "Critical", "confidence": "likely"}) is False


def test_dismissal_reason_codes_are_a_closed_set() -> None:
    """#355 — dismissal records a structured reason code."""
    module = load_module("mergecraft.findings.materiality")
    codes = getattr(module, "DISMISSAL_REASON_CODES", None)
    assert codes is not None
    frozen = frozenset(codes)
    assert "false_positive" in frozen
    record = require_callable(module, "record_dismissal")(
        fingerprint="fp-1",
        reason_code="false_positive",
    )
    code = getattr(record, "reason_code", None) or getattr(record, "code", None)
    assert str(code) == "false_positive"


def test_dismissal_feeds_evaluation_not_durable_memory(tmp_path: Path) -> None:
    """#355 out of scope — dismissal is an eval signal, not memory, until W13."""
    module = load_module("mergecraft.findings.materiality")
    record_dismissal = require_callable(module, "record_dismissal")
    record = record_dismissal(fingerprint="fp-eval", reason_code="false_positive")
    eval_payload = require_callable(module, "dismissal_eval_records")([record])
    assert eval_payload
    learnings = tmp_path / ".mergecraft" / "learnings.md"
    learnings.parent.mkdir(parents=True)
    learnings.write_text("# Learnings\n\n## Active\n\n", encoding="utf-8")
    to_memory = getattr(module, "dismissal_to_memory", None)
    if callable(to_memory):
        with pytest.raises((ValueError, RuntimeError, PermissionError), match=r"memory|W13|scope"):
            to_memory(record, learnings_path=learnings)
    assert "fp-eval" not in learnings.read_text(encoding="utf-8")


def test_precision_pipeline_orders_findings_by_materiality() -> None:
    """Publication path ranks security findings above style commentary (#355)."""
    from mergecraft.findings.precision_pipeline import apply_precision_pipeline

    security = make_finding(
        category="Security & Privacy",
        severity="Major",
        message="token logged",
        fingerprint="sec-pipe",
    )
    style = make_finding(
        category="Maintainability & Code Quality",
        severity="Minor",
        message="rename local",
        fingerprint="style-pipe",
    )
    ordered = apply_precision_pipeline([style, security], dedupe=False)
    assert ordered[0].fingerprint == security.fingerprint
