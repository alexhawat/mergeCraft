"""EV2 — semantic duplicate rate.

RED suite for PR EV2 (sub-wave EV2.1; implementation EV2.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

A review that reports the same defect three times in three phrasings reads as
thorough and scores as noisy. EV2.2 extends :class:`ScoreReport` with a
duplicate ledger:

- ``duplicate_finding_indexes: list[int]`` — findings that repeat an earlier
  finding. True semantic-dedup needs embeddings; the pinned contract is the
  honest approximation scoring can defend: same normalized path **and** line
  ranges overlapping within ``DEFAULT_LINE_SLACK`` (the same locality rule
  ``score_findings`` already uses to match findings to baseline issues), so a
  paraphrase at the same location counts. The first occurrence is canonical;
  every later overlapping finding is the duplicate.
- ``duplicate_rate: float`` — ``len(duplicate_finding_indexes) /
  total_reported``, ``0.0`` (never ``NaN``) when nothing was reported.

Pinned as attribute access on the existing ``ScoreReport`` — AttributeError at
RED time, collection stays clean. Keyless and pure: ``skipped: no live gate``.
"""

from __future__ import annotations

import pytest

from mergecraft.evals.scoring import ReportedFinding, score_findings

_XFAIL_EV2_2 = pytest.mark.xfail(
    reason="green after EV2.2: ScoreReport.duplicate_finding_indexes + duplicate_rate",
    strict=False,
)


@_XFAIL_EV2_2
def test_semantic_duplicates_are_counted() -> None:
    """Two differently-worded findings at the same location are semantic
    duplicates; the paraphrase is counted, the canonical first occurrence is
    not, and the rate is duplicates / total_reported."""
    findings = [
        ReportedFinding(
            path="src/app.py", start_line=10, end_line=12, message="SQL injection via f-string"
        ),
        # Same defect, other words, same place — the semantic-duplicate case.
        ReportedFinding(
            path="src/app.py",
            start_line=11,
            end_line=13,
            message="user-controlled input reaches the query unsanitized",
        ),
        ReportedFinding(
            path="src/app.py", start_line=50, end_line=52, message="unrelated: bare except"
        ),
    ]

    report = score_findings([], findings, closed_world=True)

    assert report.duplicate_finding_indexes == [1]
    assert report.duplicate_rate == pytest.approx(1 / 3)
