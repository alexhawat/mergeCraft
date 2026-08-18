"""Structured causality on blocking findings (DG1, D2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

CAUSALITY_EVIDENCE_PREFIX = "causality:"


class CausalityValidationError(ValueError):
    """Raised when a blocking finding lacks structured causality."""


def _is_blocking(finding: Finding) -> bool:
    from mergecraft.agents.gates import BLOCKING_SEVERITIES

    return finding.severity in BLOCKING_SEVERITIES


def causality_text(finding: Finding) -> str | None:
    """Return structured causality encoded in ``Finding.evidence``."""
    for item in finding.evidence:
        if item.startswith(CAUSALITY_EVIDENCE_PREFIX):
            text = item.removeprefix(CAUSALITY_EVIDENCE_PREFIX).strip()
            if text:
                return text
    return None


def validate_blocking_finding(finding: Finding) -> None:
    """Require structured causality on Critical/Major findings (D2)."""
    if not _is_blocking(finding):
        return
    if causality_text(finding) is None:
        msg = "blocking finding requires a causality field explaining why this PR caused it"
        raise CausalityValidationError(msg)


def apply_causality_policy(finding: Finding) -> Finding:
    """Downgrade findings that pre-existed outside this diff."""
    if finding.introduced_by_pr != "false" or not _is_blocking(finding):
        return finding
    return finding.model_copy(update={"severity": "Minor"})


__all__ = [
    "CAUSALITY_EVIDENCE_PREFIX",
    "CausalityValidationError",
    "apply_causality_policy",
    "causality_text",
    "validate_blocking_finding",
]
