"""Multi-round convergence metric — first-pass recall and leakage rate (RC6).

Scores a PR reviewed over rounds ``1…N`` from ledger snapshots and recorded
findings. Matching reuses :func:`mergecraft.evals.scoring.score_findings` locality
overlap (±``DEFAULT_LINE_SLACK`` lines), not fingerprint equality.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.analyzers.scope import _line_intersects_hunks, parse_diff_scope
from mergecraft.evals.scoring import (
    DEFAULT_LINE_SLACK,
    BaselineIssue,
    ReportedFinding,
    score_findings,
)
from mergecraft.findings.ledger import FindingLedger

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "PRE_W1_LEAKAGE_BASELINE_SCENARIO",
    "RECALL_PASS_W0_BASELINE",
    "ConvergenceCaseResult",
    "ConvergenceMetrics",
    "ConvergenceReport",
    "ConvergenceRound",
    "RecallPassCorpusReport",
    "build_pre_w1_leakage_round",
    "evaluate_recall_pass_corpus",
    "fold_convergence_reports",
    "score_convergence",
]

_SURFACED_STATES: Final[frozenset[str]] = frozenset({"open", "deferred"})


class ConvergenceRound(BaseModel):
    """One review round's ledger, findings, and first-reviewed diff."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    round_index: int
    ledger: FindingLedger
    findings: list[dict[str, Any]] = Field(default_factory=list)
    generated_fingerprints: list[str] = Field(default_factory=list)
    diff_text: str = ""


class ConvergenceReport(BaseModel):
    """Outcome of :func:`score_convergence` for one multi-round PR."""

    model_config = ConfigDict(extra="forbid")

    ground_truth_total: int
    ground_truth_fingerprints: list[str]
    ground_truth_attributable_to_round1: int
    round_one_attributable_fingerprints: list[str]
    first_pass_recall: float
    leakage_rate: float
    round_one_generated: int
    round_one_surfaced: int


class ConvergenceCaseResult(BaseModel):
    """One scenario's convergence outcome for corpus publication."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    report: ConvergenceReport


class ConvergenceMetrics(BaseModel):
    """Folded convergence metrics across a convergence eval corpus."""

    model_config = ConfigDict(extra="forbid")

    cases_total: int
    mean_first_pass_recall: float
    mean_leakage_rate: float
    case_results: list[ConvergenceCaseResult]


class RecallPassCorpusReport(BaseModel):
    """Recall-pass corpus gate — with vs without the deferred recall lane."""

    model_config = ConfigDict(extra="forbid")

    with_recall: ConvergenceMetrics
    without_recall: ConvergenceMetrics


_RECALL_CORPUS_DIFF = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,6 @@ def handler():
     pass
+    timeout = None
+    return timeout
diff --git a/src/util.py b/src/util.py
index 3333333..4444444 100644
--- a/src/util.py
+++ b/src/util.py
@@ -40,3 +40,5 @@ def helper():
     pass
+    cache = {}
+    return cache
"""


def _recall_corpus_body(label: str) -> str:
    return f"{label} — recall pass corpus fixture."


def _recall_case_id(index: int) -> str:
    return f"recall-pass-corpus-{index:03d}"


def _recall_corpus_cases() -> list[tuple[str, str, str]]:
    return [
        (
            _recall_case_id(1),
            _recall_corpus_body("missing timeout on retry"),
            _recall_corpus_body("unchecked null before return"),
        ),
        (
            _recall_case_id(2),
            _recall_corpus_body("race when claiming row"),
            _recall_corpus_body("retry loop never assigns timeout"),
        ),
        (
            _recall_case_id(3),
            _recall_corpus_body("stale cache key after rename"),
            _recall_corpus_body("caller still imports removed symbol"),
        ),
    ]


def _recall_round_one(
    *,
    case_id: str,
    drafted_body: str,
    missed_body: str,
    with_recall: bool,
) -> ConvergenceRound:
    from mergecraft.review_taxonomy import finding_fingerprint

    path = "src/app.py"
    drafted_fp = finding_fingerprint(path=path, body=drafted_body)
    missed_fp = finding_fingerprint(path="src/util.py", body=missed_body)
    drafted_row = {
        "fingerprint": drafted_fp,
        "path": path,
        "start_line": 12,
        "end_line": 12,
        "body": drafted_body,
    }
    missed_row = {
        "fingerprint": missed_fp,
        "path": "src/util.py",
        "start_line": 42,
        "end_line": 42,
        "body": missed_body,
    }
    ledger = FindingLedger()
    ledger.record(drafted_fp, "open", source=case_id, round_index=1)
    generated = [drafted_fp]
    findings = [drafted_row]
    if with_recall:
        ledger.record(missed_fp, "deferred", source=case_id, round_index=1)
        generated.append(missed_fp)
        findings.append(missed_row)
    return ConvergenceRound(
        round_index=1,
        ledger=ledger,
        findings=findings,
        generated_fingerprints=generated,
        diff_text=_RECALL_CORPUS_DIFF,
    )


def _recall_round_two(*, case_id: str, missed_body: str) -> ConvergenceRound:
    from mergecraft.review_taxonomy import finding_fingerprint

    missed_fp = finding_fingerprint(path="src/util.py", body=missed_body)
    ledger = FindingLedger()
    ledger.record(missed_fp, "open", source=case_id, round_index=2)
    return ConvergenceRound(
        round_index=2,
        ledger=ledger,
        findings=[
            {
                "fingerprint": missed_fp,
                "path": "src/util.py",
                "start_line": 42,
                "end_line": 42,
                "body": missed_body,
            }
        ],
        generated_fingerprints=[missed_fp],
        diff_text=_RECALL_CORPUS_DIFF,
    )


def _score_recall_corpus(*, with_recall: bool) -> ConvergenceMetrics:
    case_results: list[ConvergenceCaseResult] = []
    for case_id, drafted, missed in _recall_corpus_cases():
        report = score_convergence(
            [
                _recall_round_one(
                    case_id=case_id,
                    drafted_body=drafted,
                    missed_body=missed,
                    with_recall=with_recall,
                ),
                _recall_round_two(case_id=case_id, missed_body=missed),
            ]
        )
        case_results.append(ConvergenceCaseResult(case_id=case_id, report=report))
    return fold_convergence_reports(case_results)


def evaluate_recall_pass_corpus() -> RecallPassCorpusReport:
    """Score the structural recall-pass corpus with and without deferred recall."""
    without_recall = _score_recall_corpus(with_recall=False)
    with_recall = _score_recall_corpus(with_recall=True)
    return RecallPassCorpusReport(with_recall=with_recall, without_recall=without_recall)


RECALL_PASS_W0_BASELINE: Final[ConvergenceMetrics] = ConvergenceMetrics(
    cases_total=3,
    mean_first_pass_recall=0.5,
    mean_leakage_rate=0.0,
    case_results=[],
)


def _normalize_path(value: str) -> str:
    text = value.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


def _line_bounds(row: dict[str, Any]) -> tuple[int, int]:
    try:
        start = int(row.get("start_line") or row.get("line") or 1)
    except (TypeError, ValueError):  # fmt: skip
        start = 1
    try:
        end = int(row.get("end_line") or start)
    except (TypeError, ValueError):  # fmt: skip
        end = start
    if end < start:
        start, end = end, start
    return start, end


def _to_baseline(issue_id: str, row: dict[str, Any]) -> BaselineIssue:
    start, end = _line_bounds(row)
    return BaselineIssue(
        id=issue_id,
        path=_normalize_path(str(row.get("path") or "")),
        start_line=start,
        end_line=end,
        title=str(row.get("body") or row.get("message") or ""),
    )


def _to_reported(row: dict[str, Any]) -> ReportedFinding:
    start, end = _line_bounds(row)
    return ReportedFinding(
        path=_normalize_path(str(row.get("path") or "")),
        start_line=start,
        end_line=end,
        message=str(row.get("body") or row.get("message") or ""),
    )


def _ledger_state(ledger: FindingLedger, fingerprint: str) -> str | None:
    for record in ledger.records():
        if record.fingerprint == fingerprint:
            return record.state
    return None


def _is_surfaced(ledger: FindingLedger, fingerprint: str) -> bool:
    state = _ledger_state(ledger, fingerprint)
    return state in _SURFACED_STATES


def _round_by_index(
    rounds: Sequence[ConvergenceRound], round_index: int
) -> ConvergenceRound | None:
    for round_row in rounds:
        if round_row.round_index == round_index:
            return round_row
    return None


def _attributable_to_round1(
    finding: dict[str, Any],
    *,
    round_one_diff: str,
) -> bool:
    if not round_one_diff.strip():
        return True
    scope = parse_diff_scope(round_one_diff)
    path = _normalize_path(str(finding.get("path") or ""))
    start, end = _line_bounds(finding)
    return _line_intersects_hunks(path, start, end, scope)


def _issues_overlap(first: BaselineIssue, second: BaselineIssue, *, slack: int) -> bool:
    """True when two baseline rows share a path and overlapping line spans."""
    if not first.path or first.path != second.path:
        return False
    return (
        second.start_line <= first.end_line + slack and first.start_line - slack <= second.end_line
    )


def _cluster_attributable_fingerprints(
    ground_truth_by_fp: dict[str, dict[str, Any]],
    attributable_fps: list[str],
    *,
    slack: int,
) -> list[str]:
    """Collapse locality-overlapping ground-truth rows to one canonical fingerprint."""
    canonical: list[str] = []
    for fingerprint in sorted(attributable_fps):
        candidate = _to_baseline(fingerprint, ground_truth_by_fp[fingerprint])
        if any(
            _issues_overlap(
                _to_baseline(representative, ground_truth_by_fp[representative]),
                candidate,
                slack=slack,
            )
            for representative in canonical
        ):
            continue
        canonical.append(fingerprint)
    return canonical


def score_convergence(
    rounds: Sequence[ConvergenceRound],
    *,
    slack: int = DEFAULT_LINE_SLACK,
) -> ConvergenceReport:
    """Score first-pass recall and leakage from ledger snapshots alone."""
    ground_truth_by_fp: dict[str, dict[str, Any]] = {}
    for round_row in rounds:
        for finding in round_row.findings:
            fingerprint = str(finding.get("fingerprint") or "").strip()
            if fingerprint:
                ground_truth_by_fp.setdefault(fingerprint, finding)

    ground_truth_fingerprints = sorted(ground_truth_by_fp)
    round_one = _round_by_index(rounds, 1)
    round_one_diff = round_one.diff_text if round_one is not None else ""

    line_attributable = [
        fingerprint
        for fingerprint in ground_truth_fingerprints
        if _attributable_to_round1(
            ground_truth_by_fp[fingerprint],
            round_one_diff=round_one_diff,
        )
    ]
    round_one_attributable = _cluster_attributable_fingerprints(
        ground_truth_by_fp,
        line_attributable,
        slack=slack,
    )

    attributable_issues = [
        _to_baseline(fp, ground_truth_by_fp[fp]) for fp in round_one_attributable
    ]

    surfaced_findings: list[ReportedFinding] = []
    round_one_generated = 0
    round_one_surfaced = 0
    if round_one is not None:
        generated = list(round_one.generated_fingerprints)
        if not generated:
            generated = [
                str(row.get("fingerprint") or "").strip()
                for row in round_one.findings
                if str(row.get("fingerprint") or "").strip()
            ]
        round_one_generated = len(generated)
        finding_by_fp = {
            str(row.get("fingerprint") or "").strip(): row
            for row in round_one.findings
            if str(row.get("fingerprint") or "").strip()
        }
        for fingerprint in generated:
            if _is_surfaced(round_one.ledger, fingerprint):
                round_one_surfaced += 1
                row = finding_by_fp.get(fingerprint)
                if row is not None:
                    surfaced_findings.append(_to_reported(row))

    recall_report = score_findings(attributable_issues, surfaced_findings, slack=slack)
    leakage_rate = 0.0
    if round_one_generated > 0:
        leakage_rate = (round_one_generated - round_one_surfaced) / round_one_generated

    return ConvergenceReport(
        ground_truth_total=len(ground_truth_fingerprints),
        ground_truth_fingerprints=ground_truth_fingerprints,
        ground_truth_attributable_to_round1=len(round_one_attributable),
        round_one_attributable_fingerprints=round_one_attributable,
        first_pass_recall=recall_report.recall,
        leakage_rate=leakage_rate,
        round_one_generated=round_one_generated,
        round_one_surfaced=round_one_surfaced,
    )


def build_pre_w1_leakage_round() -> ConvergenceRound:
    """Synthetic round-one scenario modelling RC1/RC2 pre-W1 overflow leakage."""
    from mergecraft.review_taxonomy import finding_fingerprint

    path = "src/app.py"
    bodies = [
        f"inline overflow fixture {index} — pre-W1 leakage baseline" for index in range(1, 12)
    ]
    fingerprints = [finding_fingerprint(path=path, body=body) for body in bodies]
    findings = [
        {
            "fingerprint": fp,
            "path": path,
            "start_line": 10 + index,
            "end_line": 10 + index,
            "body": body,
        }
        for index, (fp, body) in enumerate(zip(fingerprints, bodies, strict=True))
    ]
    ledger = FindingLedger()
    for index, fingerprint in enumerate(fingerprints):
        if index < 8:
            ledger.record(fingerprint, "open", source="test", round_index=1)
        else:
            ledger.record(fingerprint, "unpublished", source="test", round_index=1)
    diff_text = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,14 @@ def handler():
     pass
+    # eleven agent findings generated; only eight inline slots
"""
    return ConvergenceRound(
        round_index=1,
        ledger=ledger,
        findings=findings,
        generated_fingerprints=fingerprints,
        diff_text=diff_text,
    )


PRE_W1_LEAKAGE_BASELINE_SCENARIO: Final[str] = "pre-w1-overflow-leakage"


def fold_convergence_reports(
    case_results: list[ConvergenceCaseResult],
) -> ConvergenceMetrics:
    """Fold per-case convergence reports into corpus-wide means."""
    total = len(case_results)
    if total == 0:
        return ConvergenceMetrics(
            cases_total=0,
            mean_first_pass_recall=1.0,
            mean_leakage_rate=0.0,
            case_results=[],
        )
    mean_recall = sum(row.report.first_pass_recall for row in case_results) / total
    mean_leakage = sum(row.report.leakage_rate for row in case_results) / total
    return ConvergenceMetrics(
        cases_total=total,
        mean_first_pass_recall=mean_recall,
        mean_leakage_rate=mean_leakage,
        case_results=case_results,
    )
