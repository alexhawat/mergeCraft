"""EV2 — blocker precision scored separately from overall precision.

RED suite for PR EV2 (sub-wave EV2.1; implementation EV2.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

Merge gating deserves its own number (plan §EV2.1): a review that is precise
overall but wrong on blocker-severity findings is a materially worse gate than
the overall figure shows. EV2.2 extends :class:`ScoreReport` with
``blocker_precision: float | None``:

- **Blocker** = a finding whose severity normalizes to ``"Critical"`` via
  :func:`mergecraft.evals.scoring.normalize_severity` (``blocker``/``critical``
  both map there) — the taxonomy's top band, reused rather than re-invented
  (global convention 4).
- ``blocker_precision`` = (blocker-severity findings that matched a baseline
  issue) / (blocker-severity findings reported). ``None`` — never a fabricated
  number — when the run reported no blocker-severity findings (the honest-
  ``None`` precedent is ``DetectionCaseResult.strict_precision``).

Pinned as attribute access on the existing ``ScoreReport`` — AttributeError at
RED time, collection stays clean, and EV2.2 chooses the storage (field or
derived property). Keyless and pure: ``score_findings`` needs no provider, so
``skipped: no live gate``.

Reconciled post-EV2.2 (2026-08-17): EV2.2 (commit ``3d64488``) made all tests
in this file XPASS; the non-strict ``green after EV2.2`` xfail markers were
removed, so every test here is now a clean real pass.

"""

from __future__ import annotations

import pytest

from mergecraft.evals.scoring import (
    BaselineIssue,
    ReportedFinding,
    score_findings,
)


def _issue(identifier: str, *, start: int, severity: str) -> BaselineIssue:
    return BaselineIssue(
        id=identifier, path="src/app.py", start_line=start, end_line=start + 1, severity=severity
    )


def _finding(*, start: int, severity: str, path: str = "src/app.py") -> ReportedFinding:
    return ReportedFinding(path=path, start_line=start, end_line=start + 1, severity=severity)


# ── blocker precision is its own number ──


def test_scored_separately_from_overall_precision() -> None:
    """One blocker found + two unmatched non-blocker findings: overall
    corpus-confirmed precision is 1/3, blocker precision is a perfect 1.0 —
    the two numbers must move independently."""
    issues = [
        _issue("blk-1", start=10, severity="blocker"),
        _issue("min-1", start=110, severity="minor"),
    ]
    findings = [
        _finding(start=10, severity="critical"),  # matches blk-1
        _finding(start=50, severity="minor", path="src/other.py"),  # unmatched
        _finding(start=70, severity="low", path="src/third.py"),  # unmatched
    ]

    report = score_findings(issues, findings, closed_world=True)

    assert report.corpus_confirmed_precision == pytest.approx(1 / 3)
    assert report.blocker_precision == pytest.approx(1.0)
    assert report.blocker_precision != report.corpus_confirmed_precision


def test_blocker_precision_regression_is_detectable() -> None:
    """Two runs with *identical* overall precision but the blocker band
    regressed: run B matched the minor issue and leaked an unmatched blocker
    finding instead. The overall figure cannot see the regression; the
    blocker figure must."""
    issues = [
        _issue("blk-1", start=10, severity="blocker"),
        _issue("min-1", start=110, severity="minor"),
    ]
    run_a = score_findings(
        issues,
        [
            _finding(start=10, severity="critical"),  # matches blk-1
            _finding(start=50, severity="minor", path="src/other.py"),  # unmatched
        ],
        closed_world=True,
    )
    run_b = score_findings(
        issues,
        [
            _finding(start=110, severity="minor"),  # matches min-1
            _finding(start=90, severity="critical", path="src/other.py"),  # unmatched blocker
        ],
        closed_world=True,
    )

    assert run_a.corpus_confirmed_precision == pytest.approx(0.5)
    assert run_b.corpus_confirmed_precision == pytest.approx(0.5)
    assert run_a.blocker_precision == pytest.approx(1.0)
    assert run_b.blocker_precision == pytest.approx(0.0)
    assert run_a.blocker_precision > run_b.blocker_precision
