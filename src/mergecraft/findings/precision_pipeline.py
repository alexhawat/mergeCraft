"""DG1 precision pipeline — compose dedup, rubric, causality, and materiality."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from mergecraft.findings.causality import apply_causality_policy
from mergecraft.findings.dedup import dedupe_findings
from mergecraft.findings.materiality import prioritize_findings
from mergecraft.findings.severity_rubric import apply_severity_rubric

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.finding import Finding


def apply_precision_pipeline(
    findings: list[Finding],
    *,
    dedupe: bool = True,
    enforce_causality: bool = False,
    repo_root: Path | None = None,
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
) -> list[Finding]:
    """Run DG1 precision transforms before publication or scoring."""
    from mergecraft.findings.causality import validate_blocking_finding

    refined = dedupe_findings(findings) if dedupe else list(findings)
    adjusted: list[Finding] = []
    for finding in refined:
        finding = apply_severity_rubric(finding)
        finding = apply_causality_policy(finding)
        if enforce_causality:
            validate_blocking_finding(finding)
        adjusted.append(finding)
    if repo_root is not None:
        from mergecraft.utils.learnings import apply_repo_memory_to_findings

        adjusted = apply_repo_memory_to_findings(
            adjusted,
            repo_root=repo_root,
            trust_tier=trust_tier,
        )
    return list(prioritize_findings(adjusted))


__all__ = ["apply_precision_pipeline"]
