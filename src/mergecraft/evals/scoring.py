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
    Breakdown: Per-category/per-severity issue and match counts.
    ScoreReport: Recall, precision, F1, the FP ledger and the per-issue breakdown.
    AggregateScoreReport: Many per-case ScoreReports folded into one corpus-wide report.
    load_baseline_issues: Parse baseline rows from a JSON payload.
    load_reported_findings: Parse review output from a JSON payload.
    score_findings: Match reported findings against baseline issues.
    fold_score_reports: Fold many per-case ScoreReports into one AggregateScoreReport.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Final

from pydantic import BaseModel, ConfigDict, Field, field_validator

from mergecraft.review_taxonomy import FINDING_CATEGORIES, FINDING_SEVERITIES

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = [
    "AggregateScoreReport",
    "BaselineIssue",
    "Breakdown",
    "JudgeValue",
    "LensValue",
    "Match",
    "ReportedFinding",
    "ScoreReport",
    "fold_score_reports",
    "judge_value",
    "load_baseline_issues",
    "load_reported_findings",
    "normalize_severity",
    "score_findings",
    "unique_accepted_findings_per_lens",
]

# Catch-all buckets for a category/severity that does not fall into
# review_taxonomy's fixed vocabulary (e.g. blank, or a corpus-specific label)
# — keeps `sum(by_category.values()) == total_issues` true unconditionally.
_UNCATEGORIZED: Final[str] = "Uncategorized"
_UNKNOWN_SEVERITY: Final[str] = "Unknown"

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


class Breakdown(BaseModel):
    """Issue and match counts for one ``by_category`` / ``by_severity`` bucket."""

    model_config = ConfigDict(extra="forbid")

    total_issues: int = 0
    found: int = 0


class ScoreReport(BaseModel):
    """The outcome of scoring one review run against one baseline."""

    model_config = ConfigDict(extra="forbid")

    total_issues: int
    total_reported: int
    matches: list[Match]
    missed_issue_ids: list[str]
    unmatched_finding_indexes: list[int]
    # Echoes the `closed_world` argument `score_findings()` was called with,
    # so `.strict_precision` knows whether every ground-truth issue in this
    # case is known (D4). Does not change how `matches` are computed.
    closed_world: bool = False
    # Per-`review_taxonomy.FINDING_CATEGORIES` issue/match counts. Sums back
    # to `total_issues` / `found` (D9 — reproducible from its parts).
    by_category: dict[str, Breakdown] = Field(default_factory=dict)
    # Per-`review_taxonomy.FINDING_SEVERITIES` issue/match counts. Sums back
    # to `total_issues` / `found` (D9).
    by_severity: dict[str, Breakdown] = Field(default_factory=dict)
    # EV2: precision over the blocker band only (findings whose severity
    # normalizes to "Critical" via `normalize_severity`) — merge gating
    # deserves its own number, since it can regress while overall precision
    # holds. `None` — never a fabricated number — when the run reported no
    # blocker-severity findings (honest-None precedent:
    # `DetectionCaseResult.strict_precision`). Defaulted so reports scored
    # before EV2 still validate.
    blocker_precision: float | None = None
    # EV2: indexes of findings that repeat an earlier finding — same
    # normalized path and line ranges overlapping within the scoring slack
    # (the locality rule `score_findings` already uses). The first occurrence
    # is canonical; every later overlapping finding lands here.
    duplicate_finding_indexes: list[int] = Field(default_factory=list)

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
    def corpus_confirmed_precision(self) -> float:
        """Fraction of reported findings that hit a baseline issue.

        This is a **lower bound on usefulness, not a false-positive rate**: a
        corpus labels the issues a human chose to record, so a real defect the
        human never wrote down scores here as unmatched. Read it as "how much of
        the output is corpus-confirmed", never as "the rest is noise". Safe on
        any corpus, open- or closed-world (D4).
        """
        if self.total_reported == 0:
            return 1.0
        return len(self.matches) / self.total_reported

    @property
    def precision(self) -> float:
        """Deprecated alias for :attr:`corpus_confirmed_precision` (D3: kept
        byte-compatible for ``mergecraft eval score`` output and older callers)."""
        return self.corpus_confirmed_precision

    @property
    def false_negatives(self) -> int:
        """Baseline issues no reported finding located."""
        return len(self.missed_issue_ids)

    @property
    def false_positives(self) -> int:
        """Unmatched findings confirmed as noise. Only nonzero on a
        closed-world report, where every ground-truth issue is known and an
        unmatched finding is therefore confirmed wrong, not merely unlabelled
        (D4/D5)."""
        return len(self.unmatched_finding_indexes) if self.closed_world else 0

    @property
    def unadjudicated(self) -> int:
        """Unmatched findings not yet judged. The honest bucket on an
        open-world corpus, where an unmatched finding may be a real defect the
        human baseline simply never recorded (D5)."""
        return 0 if self.closed_world else len(self.unmatched_finding_indexes)

    @property
    def f1(self) -> float:
        """Harmonic mean of recall and ``corpus_confirmed_precision``. ``0.0``
        (never ``NaN``) when both are zero."""
        precision, recall = self.corpus_confirmed_precision, self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)

    @property
    def strict_precision(self) -> float:
        """TP / (TP + false_positives). Defined **only** on a closed-world
        report, where every unmatched finding is a confirmed false positive
        rather than merely unadjudicated (D4). Raises on an open-world report."""
        if not self.closed_world:
            raise ValueError(
                "strict_precision is only defined on a closed-world report (D4); "
                "call score_findings(..., closed_world=True) for a fully-labelled case"
            )
        denominator = self.found + self.false_positives
        if denominator == 0:
            return 1.0
        return self.found / denominator

    @property
    def severity_agreement(self) -> float:
        """Fraction of matches whose severity equals the baseline's."""
        if not self.matches:
            return 1.0
        return sum(1 for m in self.matches if m.severity_agrees) / len(self.matches)

    @property
    def duplicate_rate(self) -> float:
        """Fraction of reported findings that duplicate an earlier finding.

        ``0.0`` (never ``NaN``) when nothing was reported.
        """
        if self.total_reported == 0:
            return 0.0
        return len(self.duplicate_finding_indexes) / self.total_reported


class LensValue(BaseModel):
    """One lens's contribution to a corpus run (EV2).

    A lens (one review agent/perspective) earns its cost only by finding
    things no other lens found. ``accepted`` counts baseline issues this
    lens's run located; ``unique_accepted`` counts located issues **no other
    lens's** run located. A lens with zero unique value is present with
    zeros — visible as a zero, never omitted (a missing key reads as
    "not run", which is a different claim).
    """

    model_config = ConfigDict(extra="forbid")

    lens: str
    accepted: int
    unique_accepted: int


class JudgeValue(BaseModel):
    """What a judge pass did to a run's score (EV2).

    A judge that improves precision only by destroying recall must look bad,
    so both halves of the trade are reported: ``noise_removed`` (false
    positives filtered out) and ``recall_lost`` (baseline issues the
    pre-judge run located that the post-judge run no longer does).
    """

    model_config = ConfigDict(extra="forbid")

    noise_removed: int
    recall_lost: int


def unique_accepted_findings_per_lens(
    findings_by_lens: dict[str, list[ReportedFinding]],
    issues: list[BaselineIssue],
    *,
    slack: int = DEFAULT_LINE_SLACK,
) -> dict[str, LensValue]:
    """Score each lens's run against the baseline and count its unique value (EV2).

    ``score_findings``' matching is one-to-one within a single run, so
    "unique" is only meaningful **across** per-lens runs: an issue is unique
    to a lens when no other lens's run located it. The ``findings_by_lens``
    key is the lens attribution (production tags findings with it — global
    convention 7); every submitted lens is a key in the result, even one
    that contributed nothing.
    """
    matched_by_lens: dict[str, set[str]] = {}
    for lens, findings in findings_by_lens.items():
        report = score_findings(issues, findings, slack=slack)
        matched_by_lens[lens] = {match.issue_id for match in report.matches}

    values: dict[str, LensValue] = {}
    for lens, issue_ids in matched_by_lens.items():
        others = set().union(*(ids for other, ids in matched_by_lens.items() if other != lens))
        values[lens] = LensValue(
            lens=lens,
            accepted=len(issue_ids),
            unique_accepted=len(issue_ids - others),
        )
    return values


def judge_value(before: ScoreReport, after: ScoreReport) -> JudgeValue:
    """Compare the pre-judge and post-judge scorings of one run (EV2).

    Pure before/after over two ``ScoreReport``\\ s of the same run:
    ``noise_removed`` is the drop in unmatched (false-positive) findings;
    ``recall_lost`` counts baseline issues located before but not after.
    """
    noise_removed = len(before.unmatched_finding_indexes) - len(after.unmatched_finding_indexes)
    before_found = {match.issue_id for match in before.matches}
    after_found = {match.issue_id for match in after.matches}
    return JudgeValue(
        noise_removed=noise_removed,
        recall_lost=len(before_found - after_found),
    )


class AggregateScoreReport(BaseModel):
    """Many per-case :class:`ScoreReport`\\ s folded into one corpus-wide report.

    ``false_positives_per_case`` and ``clean_case_fp_rate`` average only over
    the closed-world subset of the folded reports: an open-world case can
    never confirm a false positive (D4), so folding one in as a diluting zero
    would measure corpus composition rather than false-positive behaviour.
    """

    model_config = ConfigDict(extra="forbid")

    total_cases: int
    total_issues: int
    total_reported: int
    found: int
    false_negatives: int
    unadjudicated: int
    false_positives: int
    # Mean `false_positives` across the closed-world subset only. `0.0` when
    # the fold has no closed-world case (D4).
    false_positives_per_case: float
    # Fraction of closed-world cases with at least one false positive. `0.0`
    # when the fold has no closed-world case (D4).
    clean_case_fp_rate: float
    by_category: dict[str, Breakdown] = Field(default_factory=dict)
    by_severity: dict[str, Breakdown] = Field(default_factory=dict)

    @property
    def recall(self) -> float:
        """Fraction of baseline issues located, across every folded case."""
        if self.total_issues == 0:
            return 1.0
        return self.found / self.total_issues

    @property
    def corpus_confirmed_precision(self) -> float:
        """Fraction of reported findings that hit a baseline issue, across
        every folded case. See :attr:`ScoreReport.corpus_confirmed_precision`."""
        if self.total_reported == 0:
            return 1.0
        return self.found / self.total_reported

    @property
    def f1(self) -> float:
        """Harmonic mean of ``recall`` and ``corpus_confirmed_precision``.
        ``0.0`` (never ``NaN``) when both are zero."""
        precision, recall = self.corpus_confirmed_precision, self.recall
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


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
        except (TypeError, ValueError):  # fmt: skip
            start, end = 1, 1
    else:
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


def _findings_overlap(first: ReportedFinding, second: ReportedFinding, *, slack: int) -> bool:
    """True when two findings share a normalized path and their line spans
    touch within ``slack`` — the same locality rule `_overlaps` uses to match
    a finding to a baseline issue, reused for duplicate detection (EV2)."""
    if first.path != second.path:
        return False
    return (
        second.start_line <= first.end_line + slack and first.start_line - slack <= second.end_line
    )


def _empty_breakdowns() -> tuple[dict[str, Breakdown], dict[str, Breakdown]]:
    """Pre-seed one zero-count bucket per known category and severity.

    Every ``review_taxonomy`` value is present up front (even at zero) so a
    corpus that happens to use every category still reports exactly that
    vocabulary — see ``test_by_category_keys_use_the_review_taxonomy_vocabulary``.

    B1.0 design-gate reconciliation: this is deliberately a different, orthogonal
    vocabulary from ``benchmark.py``'s ``corpus_class_for()`` four buckets
    (``correctness`` / ``security`` / ``cross_file`` / ``adversarial_noop``).
    ``FINDING_CATEGORIES`` classifies an individual finding (this module operates
    at finding granularity and has no notion of a benchmark *case*);
    ``corpus_class_for()`` classifies a whole bank case by its
    ``bench-<class>-<slug>`` id prefix, for decision-replay gate metrics (B2). A
    published report shows both side by side (B7's "Detection" vs "By class"
    sections) rather than merging them into one taxonomy.
    """
    by_category = {category: Breakdown() for category in FINDING_CATEGORIES}
    by_severity = {severity: Breakdown() for severity in FINDING_SEVERITIES}
    return by_category, by_severity


def _record_issue(
    issue: BaselineIssue,
    *,
    matched: bool,
    by_category: dict[str, Breakdown],
    by_severity: dict[str, Breakdown],
) -> None:
    """Tally one baseline issue into its category and severity buckets.

    A category/severity outside the known vocabulary (including blank) falls
    into a catch-all bucket rather than being dropped, so the totals invariant
    (``sum(by_category.values()) == total_issues``) holds unconditionally.
    """
    category_key = issue.category if issue.category in FINDING_CATEGORIES else _UNCATEGORIZED
    category_bucket = by_category.setdefault(category_key, Breakdown())
    category_bucket.total_issues += 1
    if matched:
        category_bucket.found += 1

    normalized_severity = normalize_severity(issue.severity)
    severity_key = (
        normalized_severity if normalized_severity in FINDING_SEVERITIES else _UNKNOWN_SEVERITY
    )
    severity_bucket = by_severity.setdefault(severity_key, Breakdown())
    severity_bucket.total_issues += 1
    if matched:
        severity_bucket.found += 1


def score_findings(
    issues: list[BaselineIssue],
    findings: list[ReportedFinding],
    *,
    slack: int = DEFAULT_LINE_SLACK,
    closed_world: bool = False,
) -> ScoreReport:
    """Match reported findings against baseline issues by file and line overlap.

    Matching is one-to-one and greedy by proximity: each baseline issue claims
    the closest not-yet-claimed finding that overlaps it. One finding therefore
    cannot satisfy two baseline issues, so a single sprawling comment covering a
    whole file scores one match rather than all of them.

    ``closed_world`` marks this case as fully labelled — every issue a human
    would flag is already in ``issues`` — so an unmatched finding is a
    confirmed false positive rather than merely unadjudicated (D4/D5). It
    lives here, not on ``BaselineIssue``, because a clean closed-world case
    has zero baseline issues to carry a per-issue flag.
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

    matched_ids = {match.issue_id for match in matches}
    by_category, by_severity = _empty_breakdowns()
    for issue in issues:
        _record_issue(
            issue,
            matched=issue.id in matched_ids,
            by_category=by_category,
            by_severity=by_severity,
        )

    # EV2 blocker band: severity normalizing to "Critical" via
    # `normalize_severity` (blocker/critical both map there) — the taxonomy's
    # top band, reused rather than re-invented (global convention 4).
    blocker_indexes = {
        index
        for index, finding in enumerate(findings)
        if normalize_severity(finding.severity) == "Critical"
    }
    blocker_precision: float | None = None
    if blocker_indexes:
        matched_blockers = sum(1 for match in matches if match.finding_index in blocker_indexes)
        blocker_precision = matched_blockers / len(blocker_indexes)

    # EV2 duplicate ledger: the first occurrence is canonical; every later
    # finding overlapping an earlier one at the same normalized path (within
    # slack) is the duplicate — so a paraphrase at the same location counts.
    duplicate_finding_indexes = [
        index
        for index, finding in enumerate(findings)
        if any(_findings_overlap(earlier, finding, slack=slack) for earlier in findings[:index])
    ]

    return ScoreReport(
        total_issues=len(issues),
        total_reported=len(findings),
        matches=matches,
        missed_issue_ids=missed,
        unmatched_finding_indexes=[index for index in range(len(findings)) if index not in claimed],
        closed_world=closed_world,
        by_category=by_category,
        by_severity=by_severity,
        blocker_precision=blocker_precision,
        duplicate_finding_indexes=duplicate_finding_indexes,
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


def _merge_breakdowns(breakdowns: Iterable[dict[str, Breakdown]]) -> dict[str, Breakdown]:
    """Sum per-case ``by_category`` / ``by_severity`` dicts into one corpus-wide dict."""
    merged: dict[str, Breakdown] = {}
    for per_case in breakdowns:
        for key, value in per_case.items():
            bucket = merged.setdefault(key, Breakdown())
            bucket.total_issues += value.total_issues
            bucket.found += value.found
    return merged


def fold_score_reports(reports: list[ScoreReport]) -> AggregateScoreReport:
    """Fold many per-case :class:`ScoreReport`\\ s into one corpus-wide report.

    Each report counts as exactly one case. ``false_positives_per_case`` and
    ``clean_case_fp_rate`` are averaged over the closed-world subset only
    (D4): an open-world case's ``false_positives`` is always ``0``, so
    including it would dilute the rate by corpus composition rather than
    measure false-positive behaviour. Folding an empty list is well-defined
    and never divides by zero.
    """
    closed_world_reports = [report for report in reports if report.closed_world]

    if closed_world_reports:
        false_positives_per_case = sum(
            report.false_positives for report in closed_world_reports
        ) / len(closed_world_reports)
        clean_case_fp_rate = sum(
            1 for report in closed_world_reports if report.false_positives > 0
        ) / len(closed_world_reports)
    else:
        false_positives_per_case = 0.0
        clean_case_fp_rate = 0.0

    return AggregateScoreReport(
        total_cases=len(reports),
        total_issues=sum(report.total_issues for report in reports),
        total_reported=sum(report.total_reported for report in reports),
        found=sum(report.found for report in reports),
        false_negatives=sum(report.false_negatives for report in reports),
        unadjudicated=sum(report.unadjudicated for report in reports),
        false_positives=sum(report.false_positives for report in reports),
        false_positives_per_case=false_positives_per_case,
        clean_case_fp_rate=clean_case_fp_rate,
        by_category=_merge_breakdowns(report.by_category for report in reports),
        by_severity=_merge_breakdowns(report.by_severity for report in reports),
    )
