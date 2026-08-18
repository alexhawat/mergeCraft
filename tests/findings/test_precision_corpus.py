"""DG1 precision corpus gate — precision up, recall flat (DG1 Final).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG1).
Implementation: **DG1.2** — runs the eval bench corpus through the precision
pipeline and compares against a baseline captured on ``origin/pre-0.0.1``.
"""

from __future__ import annotations

import pytest

# Baseline captured on origin/pre-0.0.1 @ 41fc2af before DG1 lands.
# DG1.2 must beat these numbers without trading recall for precision.
_PRE_DG1_RECALL = 1.0
_PRE_DG1_PRECISION = 0.64


def test_precision_improves_without_recall_loss() -> None:
    """Precision rises on the bench corpus; recall must not fall — the gate test."""
    from mergecraft.findings.precision_corpus import (
        PRE_DG1_BASELINE,
        evaluate_dg1_precision_corpus,
    )

    assert PRE_DG1_BASELINE.recall == pytest.approx(_PRE_DG1_RECALL)
    assert PRE_DG1_BASELINE.corpus_confirmed_precision == pytest.approx(_PRE_DG1_PRECISION)

    report = evaluate_dg1_precision_corpus()

    assert report.recall >= PRE_DG1_BASELINE.recall
    assert report.corpus_confirmed_precision > PRE_DG1_BASELINE.corpus_confirmed_precision
