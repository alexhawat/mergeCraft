"""DG1 precision corpus gate — precision up, recall flat."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evals.scoring import BaselineIssue, ReportedFinding, ScoreReport, score_findings
from mergecraft.findings.precision_pipeline import apply_precision_pipeline

_PRE_DG1_RECALL: Final[float] = 1.0
_PRE_DG1_PRECISION: Final[float] = 0.64
_CORPUS_ISSUE_COUNT: Final[int] = 16
_DUPLICATE_NOISE_COUNT: Final[int] = 9


@dataclass(frozen=True, slots=True)
class PrecisionBaseline:
    """Frozen pre-DG1 metrics on the structural replay corpus."""

    recall: float
    corpus_confirmed_precision: float


PRE_DG1_BASELINE = PrecisionBaseline(
    recall=_PRE_DG1_RECALL,
    corpus_confirmed_precision=_PRE_DG1_PRECISION,
)


def _baseline_issues() -> list[BaselineIssue]:
    return [
        BaselineIssue(
            id=f"dg1-{index:03d}",
            path="src/bench/module.py",
            start_line=index * 10 + 1,
            end_line=index * 10 + 2,
            severity="Major",
            category="Functional Correctness",
        )
        for index in range(_CORPUS_ISSUE_COUNT)
    ]


def _canonical_findings() -> list[Finding]:
    return [
        make_finding(
            tool="agent",
            rule_id=f"agent:dg1-{index:03d}",
            category="Functional Correctness",
            severity="Major",
            confidence="likely",
            message=f"Defect {index} introduced by this change",
            path="src/bench/module.py",
            start_line=index * 10 + 1,
            end_line=index * 10 + 2,
            source="agent",
            introduced_by_pr="true",
            evidence=["causality: Introduced by the edited control flow in this PR"],
        )
        for index in range(_CORPUS_ISSUE_COUNT)
    ]


def _duplicate_noise(findings: list[Finding]) -> list[Finding]:
    duplicates: list[Finding] = []
    for index in range(_DUPLICATE_NOISE_COUNT):
        source = findings[index]
        duplicates.append(
            make_finding(
                tool="correctness-lens",
                rule_id=f"lens:dup-{index:03d}",
                category=source.category,
                severity=source.severity,
                confidence=source.confidence,
                message=f"This change also introduced defect {index}",
                path=source.path,
                start_line=source.start_line,
                end_line=source.end_line,
                source="agent",
                introduced_by_pr=source.introduced_by_pr,
                evidence=list(source.evidence),
            )
        )
    return duplicates


def _raw_corpus_findings() -> list[Finding]:
    canonical = _canonical_findings()
    return [*canonical, *_duplicate_noise(canonical)]


def _to_reported(findings: list[Finding]) -> list[ReportedFinding]:
    return [
        ReportedFinding(
            path=finding.path,
            start_line=finding.start_line or 1,
            end_line=finding.end_line or finding.start_line or 1,
            message=finding.message,
            severity=finding.severity,
            category=finding.category,
        )
        for finding in findings
    ]


def evaluate_dg1_precision_corpus() -> ScoreReport:
    """Score the DG1 corpus after the precision pipeline."""
    issues = _baseline_issues()
    refined = apply_precision_pipeline(_raw_corpus_findings())
    return score_findings(issues, _to_reported(refined))


def raw_corpus_score() -> ScoreReport:
    """Score the corpus before DG1 transforms — used for runtime evidence."""
    return score_findings(_baseline_issues(), _to_reported(_raw_corpus_findings()))


__all__ = [
    "PRE_DG1_BASELINE",
    "PrecisionBaseline",
    "evaluate_dg1_precision_corpus",
    "raw_corpus_score",
]
