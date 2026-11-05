"""Finding merge, identity, and row validation — a leaf with no CI import.

``evidence.findings`` orchestrates a run. ``ci.evidence`` records CI rows.
Both import this module so neither has to import the other for merge logic.
"""

from __future__ import annotations

import json
from typing import Any

from loguru import logger
from pydantic import ValidationError

from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding
from mergecraft.review_taxonomy import FINDING_SEVERITIES

_SEVERITY_RANK: dict[str, int] = {name: index for index, name in enumerate(FINDING_SEVERITIES)}
# The triage ``lite`` tier stores its findings in this compact shape (#1010).
LITE_FINDING_TOOL = "lite"
_LITE_ROW_KEYS: frozenset[str] = frozenset(
    {"tool", "rule_id", "severity", "path", "line", "message"}
)


def _strip_record_markers(text: str) -> str:
    """Drop deterministic-record markers from lite model output before it is rendered."""
    from mergecraft.findings.ledger import _strip_deterministic_record_markers

    return _strip_deterministic_record_markers(text)


def lite_row_finding(row: dict[str, Any]) -> Finding | None:
    """Expand one compact ``lite`` row into a ``Finding``; ``None`` when it is not one.

    A row qualifies only with ``tool == "lite"``, no key beyond ``tool``, ``rule_id``,
    ``severity``, ``path``, ``line`` and ``message``, and values ``make_finding``
    accepts. Expansion can only add a finding the gate reads, never remove one.
    """
    if row.get("tool") != LITE_FINDING_TOOL or not set(row) <= _LITE_ROW_KEYS:
        return None
    line = row.get("line")
    if not isinstance(line, int) or isinstance(line, bool) or line < 1:
        return None
    try:
        return make_finding(
            tool=LITE_FINDING_TOOL,
            rule_id=str(row.get("rule_id") or "lite-review"),
            category="Functional Correctness",
            severity=str(row.get("severity") or ""),
            confidence="possible",
            message=_strip_record_markers(str(row.get("message") or "")),
            path=str(row.get("path") or ""),
            start_line=line,
            end_line=line,
            source="agent",
        )
    except (FindingValidationError, ValidationError, ValueError):
        return None


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
            lite = lite_row_finding(row)
            if lite is not None:
                typed.append(lite)
                continue
            dropped += 1
            logger.warning(
                "findings loader: dropping malformed finding row id={} — failed Finding "
                "validation ({})",
                _row_identity(row),
                type(err).__name__,
            )
    return typed, dropped


def finding_dedupe_key(finding: Finding) -> str:
    """Identify one occurrence with compatible scope and causal attribution.

    Fingerprints identify wording, not occurrences. Conflicting attribution
    stays explicit: combining a pre-existing Critical with an introduced Minor
    must neither hide an introduced blocker nor invent an introduced Critical.
    """
    fingerprint = finding.fingerprint.strip() if finding.fingerprint else ""
    return json.dumps(
        [
            fingerprint or [finding.tool, finding.rule_id, finding.message],
            finding.path,
            finding.start_line,
            finding.end_line,
            finding.scope,
            finding.introduced_by_pr,
        ]
    )


def _severity_rank(finding: Finding) -> int:
    """Lower is more severe. Unknown grades sort after the taxonomy."""
    return _SEVERITY_RANK.get(finding.severity, len(_SEVERITY_RANK))


def merge_findings(*groups: list[Finding]) -> list[Finding]:
    """Concatenate finding groups, keeping the more severe duplicate identity.

    First-seen order is preserved. When fingerprints (or fallback keys)
    collide at one occurrence with compatible attribution, Major/Critical wins
    over Minor/Trivial and evidence from all copies survives.
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
            strongest = min(
                (existing, finding), key=lambda item: (_severity_rank(item), item.model_dump_json())
            )
            unique[key] = strongest.model_copy(
                update={
                    "evidence": sorted(set(existing.evidence) | set(finding.evidence)),
                    "collateral": sorted(set(existing.collateral) | set(finding.collateral)),
                }
            )
    return [unique[key] for key in order]


def merge_finding_records(
    records: list[dict[str, Any]], *, inline: bool = False
) -> list[dict[str, Any]]:
    """Union serialized analyzer occurrences, preserving malformed/unkeyed rows.

    Deferred rows use ``line`` and inline records wrap a full ``finding``. Their
    strongest compatible copy supplies presentation fields; evidence is additive.
    Sorting makes overlapping scopes independent of arrival order. Invalid rows
    remain visible for the downstream validation/drop accounting.
    """
    buckets: dict[str, list[dict[str, Any]]] = {}
    unkeyed: list[dict[str, Any]] = []
    for record in records:
        row = record.get("finding") if inline else record
        if not isinstance(row, dict) or not _mergeable_record(row):
            unkeyed.append(record)
            continue
        line = row.get("start_line", row.get("line"))
        key = json.dumps(
            [
                row["fingerprint"],
                row.get("path"),
                line,
                row.get("end_line", line),
                row.get("scope", "change"),
                row.get("introduced_by_pr", "unknown"),
            ],
            sort_keys=True,
        )
        buckets.setdefault(key, []).append(record)
    merged: list[dict[str, Any]] = []
    for key in sorted(buckets):
        members = buckets[key]

        def priority(record: dict[str, Any]) -> tuple[int, str]:
            row = record["finding"] if inline else record
            return (
                _SEVERITY_RANK.get(str(row.get("severity", "")), len(_SEVERITY_RANK)),
                json.dumps(record, sort_keys=True),
            )

        canonical = min(members, key=priority)
        result = dict(canonical)
        row = dict(canonical["finding"]) if inline else result
        evidence = {
            item
            for member in members
            for item in (member["finding"] if inline else member).get("evidence", [])
            if isinstance(item, str)
        }
        if evidence:
            row["evidence"] = sorted(evidence)
        if inline:
            result["finding"] = row
        merged.append(result)
    return merged + unkeyed


def _mergeable_record(row: dict[str, Any]) -> bool:
    """Invalid evidence must reach validation unchanged, never win a merge."""
    if not isinstance(row.get("fingerprint"), str) or not row["fingerprint"]:
        return False
    evidence = row.get("evidence", [])
    if not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence):
        return False
    if "body" not in row:
        try:
            Finding.model_validate(row)
        except (FindingValidationError, ValidationError, ValueError):
            return False
        return True
    # Deferred presentation rows intentionally have a smaller schema.
    line = row.get("line")
    severity = row.get("severity")
    scope = row.get("scope", "change")
    introduced = row.get("introduced_by_pr", "unknown")
    return (
        isinstance(row.get("body"), str)
        and isinstance(row.get("path"), str)
        and isinstance(severity, str)
        and severity in _SEVERITY_RANK
        and (line is None or (isinstance(line, int) and not isinstance(line, bool) and line > 0))
        and isinstance(scope, str)
        and scope in {"change", "run"}
        and isinstance(introduced, str)
        and introduced in {"true", "false", "unknown"}
    )


__all__ = [
    "_severity_rank",
    "finding_dedupe_key",
    "merge_finding_records",
    "merge_findings",
    "typed_findings_from_rows",
    "typed_findings_from_rows_with_drops",
]
