"""Audit-log and usage/cost export for enterprise deployments (#381).

Exports:
    export_audit_log: Serialise a list of audit-event records to JSON.
    export_usage: Serialise a list of usage/cost records to JSON.
    explain_blocking_decision: Return a human-readable explanation of a block.
"""

from __future__ import annotations

import json
from typing import Any

__all__ = [
    "explain_blocking_decision",
    "export_audit_log",
    "export_usage",
]


def _dump_records(records: list[dict[str, Any]]) -> str:
    """Serialise *records* as a JSON array (empty list → ``"[]"``)."""
    return json.dumps(records, default=str)


def export_audit_log(events: list[dict[str, Any]]) -> str:
    """Return *events* serialised as a JSON array.

    Args:
        events: Audit event records.  May be empty.

    Returns:
        A JSON string; an empty list produces ``"[]"``, never ``"null"``.
    """
    return _dump_records(events)


def export_usage(records: list[dict[str, Any]]) -> str:
    """Return *records* serialised as a JSON array.

    Args:
        records: Usage / cost records.  Each entry should carry at minimum a
            ``cost_usd`` or equivalent cost field.

    Returns:
        A JSON string; an empty list produces ``"[]"``.
    """
    return _dump_records(records)


def explain_blocking_decision(artifact: dict[str, Any]) -> str:
    """Return a human-readable explanation of a blocking decision.

    Args:
        artifact: A stored run artifact containing at least ``decision`` and
            ``artifact_id``.  Missing ``artifact_id`` raises ``ValueError``.

    Returns:
        A prose explanation mentioning the decision outcome and artifact ID.

    Raises:
        ValueError: When ``artifact_id`` is absent (artifact not stored).
    """
    artifact_id = artifact.get("artifact_id")
    if not artifact_id:
        msg = "artifact_id is required to explain a blocking decision"
        raise ValueError(msg)
    decision = artifact.get("decision", "unknown")
    reason = artifact.get("reason", "")
    parts = [f"Decision: {decision}"]
    if reason:
        parts.append(f"Reason: {reason}")
    parts.append(f"Artifact: {artifact_id}")
    return " | ".join(parts)
