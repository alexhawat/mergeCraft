"""Review publication gates for analyzer findings (D11/C3.4)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding


def filter_for_review(
    findings: list[Finding],
    *,
    verified_ids: set[str],
    require_verification: bool = False,
) -> list[Finding]:
    """Drop Critical/Major findings until the verifier confirms them (D11/C3.4)."""
    if not require_verification:
        return findings
    from mergecraft.agents.verifier import should_verify

    published: list[Finding] = []
    for finding in findings:
        if should_verify(finding) and finding.fingerprint not in verified_ids:
            continue
        published.append(finding)
    return published


__all__ = ["filter_for_review"]
