"""CE #455 RED — per-lens routing precision/recall capability numbers (D6).

Pins additive eval metrics in ``mergecraft.evals.lens_capability`` so routing
quality can be quoted from labeled diffs instead of asserted. Does not rebuild
the eval harness — scores labeled expected-vs-selected lens sets and folds them
into a diffable report.

Implementation wave CE commits ``feat(evals): emit per-lens capability numbers``.
"""

from __future__ import annotations

import math

import pytest
from tests.evals.support_lens_capability import (
    require_attr,
    require_callable,
    routing_label,
    routing_outcome,
)


def test_score_lens_routing_reports_per_lens_precision_and_recall() -> None:
    """Happy — per-lens TP/FP/FN roll up to precision and recall independently."""
    score = require_callable("score_lens_routing")
    report = score(
        [
            routing_label("auth-diff", "security", "correctness"),
            routing_label("docs-only", "copy-vs-code"),
        ],
        [
            routing_outcome("auth-diff", "security", "migration"),
            routing_outcome("docs-only", "copy-vs-code"),
        ],
    )

    by_lens = report.by_lens
    assert by_lens["security"].true_positives == 1
    assert by_lens["security"].false_positives == 0
    assert by_lens["security"].false_negatives == 0
    assert by_lens["security"].precision == pytest.approx(1.0)
    assert by_lens["security"].recall == pytest.approx(1.0)

    assert by_lens["migration"].true_positives == 0
    assert by_lens["migration"].false_positives == 1
    assert by_lens["migration"].precision == pytest.approx(0.0)

    assert by_lens["correctness"].false_negatives == 1
    assert by_lens["correctness"].recall == pytest.approx(0.0)

    assert by_lens["copy-vs-code"].precision == pytest.approx(1.0)
    assert by_lens["copy-vs-code"].recall == pytest.approx(1.0)


def test_score_lens_routing_macro_averages_participating_lenses_only() -> None:
    """Edge — macro precision/recall average lenses that fired or were expected."""
    score = require_callable("score_lens_routing")
    report = score(
        [routing_label("case-a", "security")],
        [routing_outcome("case-a", "security", "migration")],
    )

    # security: perfect; migration: precision 0; correctness never appeared.
    assert report.macro_precision == pytest.approx(0.5)
    assert report.macro_recall == pytest.approx(0.5)
    assert report.macro_f1 == pytest.approx(0.5)
    assert report.cases == 1
    assert "correctness" not in report.by_lens


def test_lens_never_selected_has_no_precision_but_can_have_recall() -> None:
    """Edge — expected-but-never-selected lens reports recall, not a fake precision."""
    score = require_callable("score_lens_routing")
    report = score(
        [routing_label("case-a", "security")],
        [routing_outcome("case-a", "migration")],
    )

    security = report.by_lens["security"]
    assert security.true_positives == 0
    assert security.false_negatives == 1
    assert security.recall == pytest.approx(0.0)
    assert security.precision is None


def test_lens_selected_but_never_expected_has_no_recall() -> None:
    """Edge — spurious selection reports precision, not a fake recall."""
    score = require_callable("score_lens_routing")
    report = score(
        [routing_label("case-a", "security")],
        [routing_outcome("case-a", "security", "migration")],
    )

    migration = report.by_lens["migration"]
    assert migration.true_positives == 0
    assert migration.false_positives == 1
    assert migration.precision == pytest.approx(0.0)
    assert migration.recall is None


def test_empty_corpus_yields_honest_zero_macro_metrics() -> None:
    """Edge — zero labeled cases never fabricate NaN macro numbers."""
    score = require_callable("score_lens_routing")
    report = score([], [])

    assert report.cases == 0
    assert report.by_lens == {}
    assert report.macro_precision == 0.0
    assert report.macro_recall == 0.0
    assert report.macro_f1 == 0.0
    for value in (report.macro_precision, report.macro_recall, report.macro_f1):
        assert not math.isnan(value)


def test_score_lens_routing_rejects_mismatched_case_ids() -> None:
    """Error — label/outcome case ids must align one-to-one."""
    score = require_callable("score_lens_routing")
    with pytest.raises(ValueError, match="case"):
        score(
            [routing_label("case-a", "security")],
            [routing_outcome("case-b", "security")],
        )


def test_lens_routing_capability_report_pins_schema_version() -> None:
    """Unit — report carries a stable schema version for diffable JSON."""
    score = require_callable("score_lens_routing")
    schema_version = require_attr("LENS_CAPABILITY_SCHEMA_VERSION")
    report = score(
        [routing_label("case-a", "security")],
        [routing_outcome("case-a", "security")],
    )
    assert report.schema_version == schema_version
