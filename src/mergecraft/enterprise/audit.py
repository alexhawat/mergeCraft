"""Audit-log and usage/cost export for enterprise deployments (#381).

Exports:
    append_audit_event: Append a structured event to the enterprise audit JSONL stream.
    record_blocking_decision: Persist a blocking-decision artifact as an audit event.
    export_audit_log: Serialise a list of audit-event records to JSON.
    export_usage: Serialise a list of usage/cost records to JSON.
    explain_blocking_decision: Return a human-readable explanation of a block.
    verify_audit_chain: Return 1-based line numbers where the hash chain breaks.
    resolve_audit_log_path: Resolve the on-disk audit JSONL path for a workspace.

The default audit sink lives outside the agent-writable workspace tree
(``MERGECRAFT_AUDIT_ROOT`` or ``~/.local/share/mergecraft/audit``). Hash
chaining detects tampering after the fact; it does not prevent it — for
threat models that include the local host, forward to an external sink
(syslog, OTLP logs, S3 object lock, etc.).

``MERGECRAFT_AUDIT_ROOT`` selects a **flat** audit sink: when set, every
workspace writes to ``$MERGECRAFT_AUDIT_ROOT/audit.jsonl`` (no per-workspace
subdirectory). When unset, each workspace gets an isolated file under
``~/.local/share/mergecraft/audit/<workspace-hash>/audit.jsonl``.

Concurrent JSONL appends use ``fcntl`` locking on POSIX; on Windows locking is
skipped (best-effort only — see ``_audit_append_lock``).
"""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.analyzers.redact import redact_secrets
from mergecraft.redaction_structured import redact_structured_value

if TYPE_CHECKING:
    from collections.abc import Iterator

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import TerminalSubmission

__all__ = [
    "AUDIT_IDENTIFIER_FIELDS",
    "AUDIT_LOG_FILENAME",
    "AUDIT_REQUIRED_EVENT_FIELDS",
    "AUDIT_STORED_EVENT_FIELDS",
    "DEFAULT_AUDIT_REL",
    "MERGECRAFT_AUDIT_ROOT_ENV",
    "append_audit_event",
    "explain_blocking_decision",
    "export_audit_log",
    "export_usage",
    "load_audit_events",
    "maybe_audit_blocking_terminal_submission",
    "record_blocking_decision",
    "resolve_audit_log_path",
    "resolve_audit_root",
    "verify_audit_chain",
]

DEFAULT_AUDIT_REL: Path = Path(".mergecraft") / "audit.jsonl"
AUDIT_LOG_FILENAME = "audit.jsonl"
MERGECRAFT_AUDIT_ROOT_ENV = "MERGECRAFT_AUDIT_ROOT"

AUDIT_REQUIRED_EVENT_FIELDS = frozenset({"event_type", "outcome", "context"})
AUDIT_IDENTIFIER_FIELDS = frozenset({"run_id", "artifact_id"})
AUDIT_STORED_EVENT_FIELDS = AUDIT_REQUIRED_EVENT_FIELDS | frozenset({"timestamp"})


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _resolve_root(root: Path | None) -> Path:
    return root if root is not None else Path.cwd()


def resolve_audit_root() -> Path:
    """Return the configured audit sink directory (not the JSONL file itself)."""
    raw = os.environ.get(MERGECRAFT_AUDIT_ROOT_ENV)
    if raw:
        return Path(raw).expanduser()
    data_home = os.environ.get("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "mergecraft" / "audit"


def resolve_audit_log_path(*, root: Path | None = None) -> Path:
    """Return the audit JSONL path for *root*'s workspace.

    When ``MERGECRAFT_AUDIT_ROOT`` is set, returns a flat
    ``<audit_root>/audit.jsonl`` shared across workspaces. Otherwise returns
    ``<data_home>/mergecraft/audit/<workspace-hash>/audit.jsonl``.
    """
    workspace = _resolve_root(root)
    audit_root = resolve_audit_root()
    if os.environ.get(MERGECRAFT_AUDIT_ROOT_ENV):
        return audit_root / AUDIT_LOG_FILENAME
    workspace_key = hashlib.sha256(str(workspace.resolve()).encode()).hexdigest()[:16]
    return audit_root / workspace_key / AUDIT_LOG_FILENAME


def _legacy_audit_path(workspace: Path) -> Path:
    return workspace / DEFAULT_AUDIT_REL


def _canonical_audit_body(record: dict[str, Any]) -> str:
    body = {key: value for key, value in record.items() if key not in {"prev", "hash"}}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _chain_hash(prev: str, canonical_body: str) -> str:
    return hashlib.sha256((prev + canonical_body).encode("utf-8")).hexdigest()


def _tail_last_nonempty_line(path: Path) -> str | None:
    """Return the last non-empty line of *path* without scanning the whole file."""
    chunk_size = 4096
    with path.open("rb") as handle:
        handle.seek(0, os.SEEK_END)
        pos = handle.tell()
        if pos == 0:
            return None
        buffer = b""
        while pos > 0:
            read_len = min(chunk_size, pos)
            pos -= read_len
            handle.seek(pos)
            buffer = handle.read(read_len) + buffer
            if pos == 0:
                candidates = buffer.splitlines()
            else:
                first_newline = buffer.find(b"\n")
                if first_newline == -1:
                    continue
                candidates = buffer[first_newline + 1 :].splitlines()
            for raw in reversed(candidates):
                if raw.strip():
                    return raw.decode("utf-8", errors="replace")
        return None


def _read_last_chain_hash(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        last_line = _tail_last_nonempty_line(path)
    except OSError:
        return ""
    if last_line is None:
        return ""
    try:
        payload = json.loads(last_line)
    except json.JSONDecodeError:
        return ""
    if isinstance(payload, dict):
        stored = payload.get("hash")
        if isinstance(stored, str):
            return stored
    return ""


@contextlib.contextmanager
def _audit_append_lock(path: Path) -> Iterator[None]:
    """Serialize concurrent JSONL appends across processes on one audit sink.

    Uses ``fcntl.flock`` on POSIX. On Windows ``fcntl`` is unavailable, so
    locking is skipped — concurrent appends may interleave; rely on external
    sinks for strict ordering on Windows hosts.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.parent / ".audit.lock"
    with lock_path.open("a+", encoding="utf-8") as handle:
        if sys.platform != "win32":
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform != "win32":
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _redact_context_value(value: Any) -> Any:
    return redact_structured_value(value, redact_string=redact_secrets)


def _validate_event_payload(event: Any) -> dict[str, Any]:
    if not isinstance(event, dict):
        msg = "audit event must be a dict"
        raise TypeError(msg)
    missing = AUDIT_REQUIRED_EVENT_FIELDS - event.keys()
    if missing:
        msg = f"missing required audit fields: {sorted(missing)}"
        raise ValueError(msg)
    if not (AUDIT_IDENTIFIER_FIELDS & event.keys()):
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
    """Append one structured audit event to the enterprise audit JSONL stream (#417).

    Concurrent appends are serialized with an ``fcntl`` lock beside the log file
    (best-effort on Windows, where locking is skipped). mergeCraft's Action runs
    one review process per workspace, so the lock mainly guards local CLI retries
    and parallel test workers.

    Args:
        event: Event payload with ``event_type``, ``outcome``, ``context``, and at
            least one of ``run_id`` / ``artifact_id``. ``timestamp`` is stamped in
            UTC when omitted. ``context`` is redacted before persistence.
        root: Workspace root. Defaults to the current working directory.
    """
    payload = _validate_event_payload(event)
    workspace = _resolve_root(root)
    path = resolve_audit_log_path(root=workspace)

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

    with _audit_append_lock(path), path.open("a", encoding="utf-8") as handle:
        prev_hash = _read_last_chain_hash(path)
        canonical = _canonical_audit_body(normalized)
        event_hash = _chain_hash(prev_hash, canonical)
        normalized["prev"] = prev_hash
        normalized["hash"] = event_hash
        line = json.dumps(normalized, ensure_ascii=False, default=str) + "\n"
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

    Raises:
        ValueError: When neither ``artifact_id`` nor ``run_id`` is available to
            identify the event (``append_audit_event`` requires at least one).
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
    if "artifact_id" not in event and "run_id" not in event:
        msg = "record_blocking_decision requires artifact_id and/or run_id"
        raise ValueError(msg)
    append_audit_event(event, root=root)


def maybe_audit_blocking_terminal_submission(
    ctx: ToolContext,
    recorded: TerminalSubmission,
) -> None:
    """Record enterprise audit for every terminal non-approve verdict (#417).

    ``approve`` submissions are omitted. ``request_changes`` and any other
    non-approve terminal verdict are persisted with ``event_type=terminal_verdict``
    so ``mergecraft audit export`` can replay the full decision surface, not only
    runs whose graded state blocks approval.

    Fail-open: audit persistence errors are logged and swallowed so a broken
    audit sink cannot block the review terminal path.
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


def _load_events_from_path(path: Path) -> list[dict[str, Any]]:
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


def _event_dedupe_key(event: dict[str, Any]) -> str:
    stored_hash = event.get("hash")
    if isinstance(stored_hash, str) and stored_hash:
        return stored_hash
    body = {key: value for key, value in event.items() if key not in {"prev", "hash"}}
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )


def _merge_audit_event_lists(
    primary: list[dict[str, Any]],
    legacy: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for event in legacy + primary:
        key = _event_dedupe_key(event)
        if key in seen:
            continue
        seen.add(key)
        merged.append(event)
    return merged


def load_audit_events(*, root: Path | None = None) -> list[dict[str, Any]]:
    """Load audit events for *root*'s workspace.

    Reads the external audit sink first, then merges legacy
    ``.mergecraft/audit.jsonl`` history when present (deduped by hash or
    canonical body) so pre-migration events are not lost on export.

    Args:
        root: Workspace root. Defaults to the current working directory.

    Returns:
        Event dicts, one per non-empty JSONL line. Missing files → ``[]``.
    """
    workspace = _resolve_root(root)
    primary = resolve_audit_log_path(root=workspace)
    primary_events = _load_events_from_path(primary)
    legacy_events = _load_events_from_path(_legacy_audit_path(workspace))
    if not primary_events:
        return legacy_events
    if not legacy_events:
        return primary_events
    return _merge_audit_event_lists(primary_events, legacy_events)


def verify_audit_chain(
    path: Path,
    *,
    expected_terminal_hash: str | None = None,
) -> list[int]:
    """Return 1-based line numbers where the audit hash chain breaks.

    Each record is expected to carry ``prev`` (previous line's hash, or ``""`` for
    the genesis record) and ``hash`` (``sha256(prev + canonical_body)`` where
    *canonical_body* is JSON with ``sort_keys=True`` excluding ``prev``/``hash``).

    When *expected_terminal_hash* is supplied (an external tip commitment from a
    checkpoint, backup, or replication source), a valid prefix that ends early
    is flagged on the last line — tail truncation is otherwise indistinguishable
    from an intact chain.

    *path* must be a regular file; callers (e.g. ``mergecraft audit verify``)
    must reject missing or non-regular paths before treating an empty result as ok.
    """
    if not path.is_file():
        return []
    breaks: list[int] = []
    prev_hash = ""
    last_line_no = 0
    last_stored_hash: str | None = None
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            breaks.append(line_no)
            continue
        if not isinstance(record, dict):
            breaks.append(line_no)
            continue
        stored_prev = record.get("prev")
        stored_hash = record.get("hash")
        canonical = _canonical_audit_body(record)
        expected_hash = _chain_hash(prev_hash, canonical)
        if stored_hash is None:
            if line_no > 1:
                breaks.append(line_no)
            prev_hash = expected_hash
            continue
        if stored_prev != prev_hash or stored_hash != expected_hash:
            breaks.append(line_no)
        prev_hash = stored_hash
        last_line_no = line_no
        last_stored_hash = stored_hash
    if (
        expected_terminal_hash is not None
        and last_line_no > 0
        and last_stored_hash is not None
        and last_stored_hash != expected_terminal_hash
        and last_line_no not in breaks
    ):
        breaks.append(last_line_no)
    return breaks


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
