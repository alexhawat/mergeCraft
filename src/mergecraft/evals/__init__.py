"""Failure Memory and Eval Bank — file-backed durable case store (#51).

Every mergeCraft run produces a :class:`mergecraft.evidence.MergeEvidencePacket`;
when a run produces a *bad* outcome (a missed finding, a rejected verdict,
a reverted PR), the operator can capture that outcome as a durable case in
the eval bank. The bank is a **local, file-backed** store — no database,
no hosted service (D13). The bank reuses the :class:`LearningProvenance`
record from the security Batch C plan (D5) so every case carries the
author/runs/PR metadata that the audit tooling expects.

The case schema is markdown + YAML front matter; the front matter is
validated by ``LearningProvenance.extra="forbid"`` (the locked invariant
from ``docs/dev/test-plans/cross-file-deps.md``), so the same parser logic
that guards the learnings file guards the eval bank.

This module is the **pure core**. The CLI in ``mergecraft.cli.eval_cmd``
is the thin I/O shell that wraps it. The store reads / writes files
when the caller hands them a path; it has no ``os.environ`` reads, no
network, and no module-level I/O at import time (§W11.6).
"""

from __future__ import annotations

from mergecraft.evals.scoring import (
    AggregateScoreReport,
    BaselineIssue,
    Breakdown,
    Match,
    ReportedFinding,
    ScoreReport,
    fold_score_reports,
    format_report,
    load_baseline_issues,
    load_reported_findings,
    score_findings,
)
from mergecraft.evals.store import (
    CASE_FILE_SUFFIX,
    CASE_STATUS_BLOCKED,
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
    CASES_DIR_NAME,
    DEFAULT_BANK_DIR,
    Case,
    CaseFilter,
    ReplayDiff,
    add_case,
    diff_cases,
    list_cases,
    load_case,
    parse_case_text,
    recompute_decision,
    render_case_text,
    replay_case,
)

__all__ = [
    "CASES_DIR_NAME",
    "CASE_FILE_SUFFIX",
    "CASE_STATUS_BLOCKED",
    "CASE_STATUS_PASSED",
    "CASE_STATUS_REGRESSION",
    "DEFAULT_BANK_DIR",
    "AggregateScoreReport",
    "BaselineIssue",
    "Breakdown",
    "Case",
    "CaseFilter",
    "Match",
    "ReplayDiff",
    "ReportedFinding",
    "ScoreReport",
    "add_case",
    "diff_cases",
    "fold_score_reports",
    "format_report",
    "list_cases",
    "load_baseline_issues",
    "load_case",
    "load_reported_findings",
    "parse_case_text",
    "recompute_decision",
    "render_case_text",
    "replay_case",
    "score_findings",
]
