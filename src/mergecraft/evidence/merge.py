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
    """Validate dict rows as ``Finding`` objects, skipping malformed ones.

    Thin wrapper over :func:`typed_findings_from_rows_with_drops` for callers
    that never needed the drop count (``ci/evidence.py``'s two call sites).
    """
    typed, _dropped = typed_findings_from_rows_with_drops(raw)
    return typed


def _row_identity(row: dict[str, Any]) -> str:
    """Best-effort identifier for a log line — never the row's own prose.

    Prefers ``fingerprint`` (stable across runs), then ``path``. Neither
    field is expected to carry review body text, unlike ``message``/``body``,
    which this helper deliberately never touches.
    """
    fingerprint = row.get("fingerprint")
    if isinstance(fingerprint, str) and fingerprint:
        return fingerprint
    path = row.get("path")
    if isinstance(path, str) and path:
        return path
    return "(no identity)"


def typed_findings_from_rows_with_drops(raw: list[Any]) -> tuple[list[Finding], int]:
    """Validate dict rows as ``Finding`` objects, skipping malformed ones.

    Identical to :func:`typed_findings_from_rows` except it also returns how
    many rows were discarded. A row that can never validate as ``Finding``
    (wrong shape, unknown extra field, missing required field — the #623
    bug: an ``AgentFinding``-shaped row stored where a ``Finding``-shaped row
    was required) was previously indistinguishable from no rows at all; the
    caller can use the count to record run-health evidence that the packet
    lost data (see :mod:`mergecraft.evidence.build`).

    A dropped row is logged at ``warning`` — this is evidence integrity, not
    routine debug noise — but never with the row's own content: a pydantic
    ``ValidationError`` raised off this model embeds the *entire* rejected
    input (including any ``message``/``body`` prose) in its own message text,
    so only the row's ``fingerprint``/``path`` and the exception's type name
    are logged, never ``str(err)`` or ``err.errors()``.
    """
    typed: list[Finding] = []
    dropped = 0
    for row in raw:
        if isinstance(row, Finding):
            typed.append(row)
            continue
        if not isinstance(row, dict):
            dropped += 1
            logger.warning(
                "findings loader: dropping finding row of type {} — not an object",
                type(row).__name__,
            )
            continue
        try:
            typed.append(Finding.model_validate(row))
        except (FindingValidationError, ValidationError, ValueError) as err:
            dropped += 1
            logger.warning(
                "findings loader: dropping malformed finding row id={} — failed Finding "
                "validation ({})",
                _row_identity(row),
                type(err).__name__,
            )
    return typed, dropped


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
    "typed_findings_from_rows_with_drops",
]
