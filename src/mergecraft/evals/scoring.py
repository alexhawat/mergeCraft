"""Locality-based scoring of review findings against a frozen baseline (#30, C7).

A review benchmark cannot score by equality. The baseline records what a human
reviewer *concluded* — a path, a line range, and a description — while a review
run produces mergeCraft's own ``Finding`` rows with their own fingerprints, rule
ids and wording. Comparing those structurally means a run fails for paraphrasing
a finding it actually located, which measures nothing.

So a baseline issue counts as **found** when a reported finding overlaps its line
range in the same file. That is the weakest claim the benchmark can make and
still be true: the reviewer looked at the right code and said something about it.
Wording, severity and category are reported as agreement metrics alongside the
match, never as match conditions.

Exports:
    BaselineIssue: One frozen expected issue.
    ReportedFinding: One finding a review run produced.
    Match: A baseline issue paired with the finding that located it.
    ScoreReport: Recall, precision and the per-issue breakdown.
    load_baseline_issues: Parse baseline rows from a JSON payload.
    load_reported_findings: Parse review output from a JSON payload.
    score_findings: Match reported findings against baseline issues.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, field_validator

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "BaselineIssue",
    "Match",
    "ReportedFinding",
    "ScoreReport",
    "load_baseline_issues",
    "load_reported_findings",
    "normalize_severity",
    "score_findings",
]

# A baseline issue anchored at a single line still deserves a match when the
# reviewer flags the statement just above or below it — reviewers legitimately
# anchor on the assignment rather than the branch that uses it.
DEFAULT_LINE_SLACK: Final[int] = 3


def _normalize_path(value: str) -> str:
    """Strip leading ``./`` and ``a/`` / ``b/`` diff prefixes from a path."""
    text = value.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


class BaselineIssue(BaseModel):
    """One frozen expected issue from a benchmark corpus."""

    model_config = ConfigDict(extra="ignore")

    id: str
    path: str
    start_line: int
    end_line: int
    title: str = ""
    severity: str = ""
    category: str = ""
    provenance: str = ""

    @field_validator("path")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return _normalize_path(value)


class ReportedFinding(BaseModel):
    """One finding produced by a review run."""

    model_config = ConfigDict(extra="ignore")

    path: str
    start_line: int
    end_line: int
    message: str = ""
    severity: str = ""
    category: str = ""

    @field_validator("path")
    @classmethod
    def _normalize(cls, value: str) -> str:
        return _normalize_path(value)


class Match(BaseModel):
    """A baseline issue paired with the reported finding that located it."""

    model_config = ConfigDict(extra="forbid")

    issue_id: str
    finding_index: int
    severity_agrees: bool
    category_agrees: bool


class ScoreReport(BaseModel):
    """The outcome of scoring one review run against one baseline."""

    model_config = ConfigDict(extra="forbid")

    total_issues: int
    total_reported: int
    matches: list[Match]
    missed_issue_ids: list[str]
    unmatched_finding_indexes: list[int]

    @property
    def found(self) -> int:
        """How many baseline issues a reported finding located."""
        return len(self.matches)

    @property
    def recall(self) -> float:
        """Fraction of baseline issues located. ``1.0`` for an empty baseline."""
        if self.total_issues == 0:
            return 1.0
        return self.found / self.total_issues

    @property
    def precision(self) -> float:
        """Fraction of reported findings that hit a baseline issue.

        This is a **lower bound on usefulness, not a false-positive rate**: a
        corpus labels the issues a human chose to record, so a real defect the
        human never wrote down scores here as unmatched. Read it as "how much of
        the output is corpus-confirmed", never as "the rest is noise".
        """
        if self.total_reported == 0:
            return 1.0
        return len(self.matches) / self.total_reported

    @property
    def severity_agreement(self) -> float:
        """Fraction of matches whose severity equals the baseline's."""
        if not self.matches:
            return 1.0
        return sum(1 for m in self.matches if m.severity_agrees) / len(self.matches)


# Benchmark corpora record severity in their own vocabulary. tripll's
# ``baseline.jsonl`` uses ``high``/``medium`` where the Harbor fixture promoted
# from the *same two issues* uses ``Major``/``Minor`` — so scoring severity
# without normalizing reports 0% agreement on a corpus that in fact agrees
# perfectly. This map is read off that promotion, not invented here.
_SEVERITY_ALIASES: Final[dict[str, str]] = {
    "critical": "Critical",
    "blocker": "Critical",
    "high": "Major",
    "major": "Major",
    "medium": "Minor",
    "moderate": "Minor",
    "minor": "Minor",
    "low": "Trivial",
    "trivial": "Trivial",
    "info": "Trivial",
    "nit": "Trivial",
}


def normalize_severity(value: str) -> str:
    """Map a corpus severity onto mergeCraft's ``FINDING_SEVERITIES`` vocabulary.

    Unknown values are returned title-cased rather than dropped, so a corpus
    using a grade this map has not seen still compares against itself.
    """
    text = value.strip().lower()
    if not text:
        return ""
    return _SEVERITY_ALIASES.get(text, value.strip().title())


def _rows(payload: Any) -> list[dict[str, Any]]:
    """Return the finding rows from either a bare list or a ``findings`` envelope."""
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("findings", "issues", "baseline"):
            value = payload.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, dict)]
        # A one-row JSONL file is itself valid JSON, so it arrives here as a bare
        # object rather than a list. Treating that as "no rows" silently scores
        # recall as a vacuous 1.0, which is the worst possible failure mode for a
        # benchmark — so recognise a lone row by its anchor fields instead.
        if "path" in payload and ("line_range" in payload or "start_line" in payload):
            return [payload]
    return []


def _line_bounds(row: dict[str, Any]) -> tuple[int, int]:
    """Return ``(start, end)`` from either explicit lines or a ``line_range``."""
    span = row.get("line_range")
    if isinstance(span, (list, tuple)) and len(span) == 2:
        try:
            start, end = int(span[0]), int(span[1])
        except TypeError, ValueError:
            start, end = 1, 1
    else:
        try:
            start = int(row.get("start_line") or row.get("line") or 1)
        except TypeError, ValueError:
            start = 1
        try:
            end = int(row.get("end_line") or start)
        except TypeError, ValueError:
            end = start
    if end < start:
        start, end = end, start
    return start, end


def load_baseline_issues(payload: Any, *, source: str = "baseline") -> list[BaselineIssue]:
    """Parse baseline issues from a decoded JSON payload.

    Accepts both corpus shapes in use: the ``baseline.jsonl``-style row with
    ``line_range`` and ``description``, and the mergeCraft ``Finding`` shape with
    ``start_line`` / ``end_line`` / ``message``.
    """
    issues: list[BaselineIssue] = []
    for index, row in enumerate(_rows(payload)):
        start, end = _line_bounds(row)
        identifier = str(row.get("id") or row.get("cluster_id") or f"{source}-{index:03d}")
        issues.append(
            BaselineIssue(
                id=identifier,
                path=_normalize_path(str(row.get("path") or "")),
                start_line=start,
                end_line=end,
                title=str(row.get("title") or row.get("message") or ""),
                severity=str(row.get("severity") or ""),
                category=str(row.get("category") or ""),
                provenance=str(row.get("provenance") or ""),
            )
        )
    return issues


def load_reported_findings(payload: Any) -> list[ReportedFinding]:
    """Parse the findings a review run reported from a decoded JSON payload."""
    findings: list[ReportedFinding] = []
    for row in _rows(payload):
        start, end = _line_bounds(row)
        findings.append(
            ReportedFinding(
                path=_normalize_path(str(row.get("path") or "")),
                start_line=start,
                end_line=end,
                message=str(row.get("message") or row.get("title") or ""),
                severity=str(row.get("severity") or ""),
                category=str(row.get("category") or ""),
            )
        )
    return findings


def _overlaps(issue: BaselineIssue, finding: ReportedFinding, *, slack: int) -> bool:
    """True when the finding's line span touches the issue's, within ``slack``."""
    if not issue.path or issue.path != finding.path:
        return False
    return (
        finding.start_line <= issue.end_line + slack
        and issue.start_line - slack <= finding.end_line
    )


def _distance(issue: BaselineIssue, finding: ReportedFinding) -> int:
    """Line distance between two spans; ``0`` when they truly overlap."""
    if finding.start_line > issue.end_line:
        return finding.start_line - issue.end_line
    if issue.start_line > finding.end_line:
        return issue.start_line - finding.end_line
    return 0


def score_findings(
    issues: list[BaselineIssue],
    findings: list[ReportedFinding],
    *,
    slack: int = DEFAULT_LINE_SLACK,
) -> ScoreReport:
    """Match reported findings against baseline issues by file and line overlap.

    Matching is one-to-one and greedy by proximity: each baseline issue claims
    the closest not-yet-claimed finding that overlaps it. One finding therefore
    cannot satisfy two baseline issues, so a single sprawling comment covering a
    whole file scores one match rather than all of them.
    """
    claimed: set[int] = set()
    matches: list[Match] = []
    missed: list[str] = []

    for issue in issues:
        candidates = [
            (index, finding)
            for index, finding in enumerate(findings)
            if index not in claimed and _overlaps(issue, finding, slack=slack)
        ]
        if not candidates:
            missed.append(issue.id)
            continue
        index, finding = min(candidates, key=lambda pair: _distance(issue, pair[1]))
        claimed.add(index)
        matches.append(
            Match(
                issue_id=issue.id,
                finding_index=index,
                severity_agrees=bool(issue.severity)
                and normalize_severity(issue.severity) == normalize_severity(finding.severity),
                category_agrees=bool(issue.category)
                and issue.category.lower() == finding.category.lower(),
            )
        )

    return ScoreReport(
        total_issues=len(issues),
        total_reported=len(findings),
        matches=matches,
        missed_issue_ids=missed,
        unmatched_finding_indexes=[index for index in range(len(findings)) if index not in claimed],
    )


def format_report(report: ScoreReport, *, corpus: Path | str = "") -> str:
    """Render a human-readable summary of a score report."""
    header = f"ReviewBench score — {corpus}" if corpus else "ReviewBench score"
    lines = [
        header,
        f"  baseline issues : {report.total_issues}",
        f"  findings reported: {report.total_reported}",
        f"  located          : {report.found}",
        f"  recall           : {report.recall:.2%}",
        f"  corpus-confirmed : {report.precision:.2%}",
    ]
    if report.matches:
        lines.append(f"  severity agree   : {report.severity_agreement:.2%}")
    if report.missed_issue_ids:
        lines.append(f"  missed           : {', '.join(report.missed_issue_ids)}")
    return "\n".join(lines)
