"""Analyzer-side precision transforms (DG1).

The analyzer pipeline applies deduplication only. Agent findings run the full
``findings.precision_pipeline`` (dedupe + severity rubric + causality policy)
before publication or judge scoring.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.dedup import dedupe_findings

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding


def apply_analyzer_precision(findings: list[Finding]) -> list[Finding]:
    """Collapse duplicate analyzer defects before clustering and budget placement."""
    return dedupe_findings(findings)


__all__ = ["apply_analyzer_precision"]
