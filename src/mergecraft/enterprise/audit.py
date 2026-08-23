"""Audit-log and usage/cost export for enterprise deployments (#381).

Exports:
    append_audit_event: Append a structured event to the enterprise audit JSONL stream.
    record_blocking_decision: Persist a blocking-decision artifact as an audit event.
    export_audit_log: Serialise a list of audit-event records to JSON.
    export_usage: Serialise a list of usage/cost records to JSON.
    explain_blocking_decision: Return a human-readable explanation of a block.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets

__all__ = [
    "DEFAULT_AUDIT_REL",
    "append_audit_event",
    "explain_blocking_decision",
    "export_audit_log",
    "export_usage",
    "load_audit_events",
    "maybe_audit_blocking_terminal_submission",
    "record_blocking_decision",
]

DEFAULT_AUDIT_REL: Path = Path(".mergecraft") / "audit.jsonl"

_REQUIRED_EVENT_FIELDS = frozenset({"event_type", "outcome", "context"})
_IDENTIFIER_FIELDS = frozenset({"run_id", "artifact_id"})


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_root(root: Path | None) -> Path:
    return root if root is not None else Path.cwd()


def _audit_path(root: Path) -> Path:
    return root / DEFAULT_AUDIT_REL


def _redact_context_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {str(key): _redact_context_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_context_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_context_value(item) for item in value]
    return value


def _validate_event_payload(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        msg = "audit event must be a dict"
        raise TypeError(msg)
    missing = _REQUIRED_EVENT_FIELDS - event.keys()
    if missing:
        msg = f"missing required audit fields: {sorted(missing)}"
        raise ValueError(msg)
    if not (_IDENTIFIER_FIELDS & event.keys()):
        msg = "audit event must include run_id and/or artifact_id"
        raise ValueError(msg)
    if not isinstance(event["context"], dict):
        msg = "audit event context must be a dict"
        raise TypeError(msg)
    return dict(event)


def append_audit_event(
    event: dict[str, Any],
    *,
    root: Path | None = None,
) -> None:
    """Append one structured audit event to ``.mergecraft/audit.jsonl`` (#417).

    Args:
        event: Event payload with ``event_type``, ``outcome``, ``context``, and at
            least one of ``run_id`` / ``artifact_id``. ``timestamp`` is stamped in
            UTC when omitted. ``context`` is redacted before persistence.
        root: Workspace root. Defaults to the current working directory.
    """
    payload = _validate_event_payload(event)
    workspace = _resolve_root(root)
    path = _audit_path(workspace)

    normalized: dict[str, Any] = {
        "timestamp": payload.get("timestamp") or _utc_now_iso(),
        "event_type": str(payload["event_type"]),
        "outcome": str(payload["outcome"]),
        "context": _redact_context_value(payload["context"]),
    }
    if "run_id" in payload:
        normalized["run_id"] = payload["run_id"]
    if "artifact_id" in payload:
        normalized["artifact_id"] = payload["artifact_id"]

    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(normalized, ensure_ascii=False, default=str) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def record_blocking_decision(
    artifact: dict[str, Any],
    *,
    run_id: str | None = None,
    root: Path | None = None,
) -> None:
    """Persist a blocking-decision artifact to the enterprise audit JSONL stream.

    Args:
        artifact: Stored run artifact with ``decision`` and ``artifact_id``.
        run_id: Optional run identifier to attach to the audit event.
        root: Workspace root. Defaults to the current working directory.
    """
    context: dict[str, Any] = {}
    reason = artifact.get("reason")
    if reason:
        context["reason"] = reason

    event: dict[str, Any] = {
        "event_type": "blocking_decision",
        "outcome": str(artifact.get("decision", "unknown")),
        "context": context,
    }
    artifact_id = artifact.get("artifact_id")
    if artifact_id is not None:
        event["artifact_id"] = artifact_id
    if run_id is not None:
        event["run_id"] = run_id
    append_audit_event(event, root=root)


def maybe_audit_blocking_terminal_submission(
    ctx: Any,
    recorded: Any,
) -> None:
    """Record enterprise audit for every terminal non-approve verdict (#417).

    ``approve`` submissions are omitted. ``request_changes`` and any other
    non-approve terminal verdict are persisted with ``event_type=terminal_verdict``
    so ``mergecraft audit export`` can replay the full decision surface, not only
    runs whose graded state blocks approval.
    """
    if recorded.verdict == "approve":
        return
    from mergecraft.mcp.tool_state import primary_repo_state

    try:
        repo_root = _resolve_root(Path(primary_repo_state(ctx.tool_state).dir))
        append_audit_event(
            {
                "event_type": "terminal_verdict",
                "outcome": str(recorded.verdict),
                "artifact_id": recorded.id,
                "run_id": ctx.tool_state.run_id,
                "context": {"summary": str(recorded.summary)},
            },
            root=repo_root,
        )
    except Exception:
        logger.warning(
            "Failed to append terminal verdict audit event for {}",
            recorded.id,
            exc_info=True,
        )


def load_audit_events(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Load audit events from ``.mergecraft/audit.jsonl`` under *root*.

    Args:
        root: Workspace root. Defaults to the current working directory.

    Returns:
        Event dicts, one per non-empty JSONL line. Missing file → ``[]``.
    """
    path = _audit_path(_resolve_root(root))
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning(
                "Skipping malformed audit JSONL line {} in {}",
                line_no,
                path,
            )
            continue
        if not isinstance(payload, dict):
            logger.warning(
                "Skipping non-dict audit JSONL payload at line {} in {}",
                line_no,
                path,
            )
            continue
        events.append(payload)
    return events


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
