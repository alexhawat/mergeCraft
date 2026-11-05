"""DG1 precision pipeline — compose dedup, rubric, causality, and materiality."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mergecraft.findings.causality import apply_causality_policy
from mergecraft.findings.dedup import DedupeResult, dedupe_findings_with_indices
from mergecraft.findings.materiality import prioritize_findings
from mergecraft.findings.severity_rubric import apply_severity_rubric

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding


@dataclass(frozen=True, slots=True)
class PrecisionResult:
    """Refined findings and their corresponding original input row indices."""

    findings: list[Finding]
    kept_indices: list[int]


def apply_precision_pipeline_with_indices(
    findings: list[Finding],
    *,
    dedupe: bool = True,
    enforce_causality: bool = False,
    repo_root: Path | None = None,
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
) -> PrecisionResult:
    """Run transforms while retaining row identity through filtering and ranking.

    A fingerprint can name several occurrences and is never a row identifier.
    Copy-producing transforms retain the source index explicitly. Memory and
    materiality only filter/reorder those transformed objects, so their object
    identities correlate results without adding internal markers to wire data.
    """
    from mergecraft.findings.causality import validate_blocking_finding

    refined = (
        dedupe_findings_with_indices(findings)
        if dedupe
        else DedupeResult(findings=list(findings), kept_indices=list(range(len(findings))))
    )
    adjusted: list[Finding] = []
    indices_by_object: dict[int, deque[int]] = defaultdict(deque)
    for source_index, finding in zip(refined.kept_indices, refined.findings, strict=True):
        finding = apply_severity_rubric(finding)
        finding = apply_causality_policy(finding)
        if enforce_causality:
            validate_blocking_finding(finding)
        adjusted.append(finding)
        indices_by_object[id(finding)].append(source_index)
    if repo_root is not None:
        from mergecraft.utils.learnings import apply_repo_memory_to_findings

        adjusted = apply_repo_memory_to_findings(
            adjusted,
            repo_root=repo_root,
            trust_tier=trust_tier,
        )
    ordered = list(prioritize_findings(adjusted))
    return PrecisionResult(
        findings=ordered,
        kept_indices=[indices_by_object[id(finding)].popleft() for finding in ordered],
    )


def apply_precision_pipeline(
    findings: list[Finding],
    *,
    dedupe: bool = True,
    enforce_causality: bool = False,
    repo_root: Path | None = None,
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
) -> list[Finding]:
    """Run DG1 precision transforms before publication or scoring."""
    return apply_precision_pipeline_with_indices(
        findings,
        dedupe=dedupe,
        enforce_causality=enforce_causality,
        repo_root=repo_root,
        trust_tier=trust_tier,
    ).findings


__all__ = ["PrecisionResult", "apply_precision_pipeline", "apply_precision_pipeline_with_indices"]
