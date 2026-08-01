"""Verification routing for CI findings attributed to the PR (K2.6 / D11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.verifier import should_verify
from mergecraft.analyzers.review_gate import filter_for_review

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding


def annotate_caused_by_pr(finding: Finding) -> Finding:
    """Mark PR-attributed CI failures as Major so they reach the verifier (D11)."""
    if finding.source != "ci":
        return finding
    return finding.model_copy(
        update={
            "severity": "Major",
            "introduced_by_pr": "true",
        }
    )


def annotate_not_caused_by_pr(finding: Finding) -> Finding:
    """Keep flaky/unrelated CI failures out of author-blame and verification."""
    if finding.source != "ci":
        return finding
    return finding.model_copy(
        update={
            "severity": "Minor",
            "introduced_by_pr": "false",
        }
    )


def requires_verification(finding: Finding) -> bool:
    """Return whether a CI finding should pass through the verifier before review."""
    return finding.source == "ci" and finding.introduced_by_pr == "true" and should_verify(finding)


def filter_ci_for_review(
    findings: list[Finding],
    *,
    verified_ids: set[str],
    require_verification: bool = False,
) -> list[Finding]:
    """Apply the shared review gate to CI findings (D11)."""
    return filter_for_review(
        findings,
        verified_ids=verified_ids,
        require_verification=require_verification,
    )


__all__ = [
    "annotate_caused_by_pr",
    "annotate_not_caused_by_pr",
    "filter_ci_for_review",
    "requires_verification",
]
