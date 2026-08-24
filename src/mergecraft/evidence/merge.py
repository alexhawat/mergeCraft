"""Finding merge, identity, and row validation — a leaf with no CI import.

``evidence.findings`` orchestrates a run. ``ci.evidence`` records CI rows.
Both import this module so neither has to import the other for merge logic.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from pydantic import ValidationError

from mergecraft.analyzers.finding import Finding, FindingValidationError
from mergecraft.review_taxonomy import FINDING_SEVERITIES

_SEVERITY_RANK: dict[str, int] = {name: index for index, name in enumerate(FINDING_SEVERITIES)}


def typed_findings_from_rows(raw: list[Any]) -> list[Finding]:
    """Validate dict rows as ``Finding`` objects, skipping malformed ones."""
    typed: list[Finding] = []
    for row in raw:
        if isinstance(row, Finding):
            typed.append(row)
            continue
        if not isinstance(row, dict):
            continue
        try:
            typed.append(Finding.model_validate(row))
        except (FindingValidationError, ValidationError, ValueError) as err:
            logger.debug("findings loader: dropping malformed finding row: {}", err)
    return typed


def finding_dedupe_key(finding: Finding) -> str:
    """Stable identity for merge: fingerprint, else tool/rule/path/line/message."""
    fingerprint = finding.fingerprint.strip() if finding.fingerprint else ""
    if fingerprint:
        return fingerprint
    return "|".join(
        (
            finding.tool,
            finding.rule_id,
            finding.path,
            str(finding.start_line or 0),
            finding.message,
        )
    )


def _severity_rank(finding: Finding) -> int:
    """Lower is more severe. Unknown grades sort after the taxonomy."""
    return _SEVERITY_RANK.get(finding.severity, len(_SEVERITY_RANK))


def merge_findings(*groups: list[Finding]) -> list[Finding]:
    """Concatenate finding groups, keeping the more severe duplicate identity.

    First-seen order is preserved. When fingerprints (or fallback keys)
    collide, Major/Critical wins over Minor/Trivial so a CI blocker is not
    dropped behind a less severe agent copy.
    """
    unique: dict[str, Finding] = {}
    order: list[str] = []
    for group in groups:
        for finding in group:
            key = finding_dedupe_key(finding)
            existing = unique.get(key)
            if existing is None:
                unique[key] = finding
                order.append(key)
                continue
            if _severity_rank(finding) < _severity_rank(existing):
                unique[key] = finding
    return [unique[key] for key in order]


__all__ = [
    "finding_dedupe_key",
    "merge_findings",
    "typed_findings_from_rows",
]
