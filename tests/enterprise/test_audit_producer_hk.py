"""Batch HK RED — audit.jsonl producer for audit export (#417).

Pins D10: append-only JSONL at ``.mergecraft/audit.jsonl`` with timestamp,
event type, decision/outcome, run/artifact ids, and redacted context.
``load_audit_events`` / ``mergecraft audit export`` stay the read path;
``policy-audit.json`` remains separate. Implementation lands in W22.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from mergecraft.enterprise.audit import DEFAULT_AUDIT_REL, load_audit_events
from mergecraft.policy.lifecycle import write_policy_audit

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}

_REQUIRED_EVENT_FIELDS = frozenset(
    {
        "timestamp",
        "event_type",
        "outcome",
        "context",
    }
)
_IDENTIFIER_FIELDS = frozenset({"run_id", "artifact_id"})
_SAMPLE_SECRET = "ghp_abcdefghijklmnopqrstuvwxyz1234567890"


def _audit_module() -> Any:
    import mergecraft.enterprise.audit as audit

    return audit


def _require_append_audit_event() -> Any:
    fn = getattr(_audit_module(), "append_audit_event", None)
    if fn is None:
        msg = "append_audit_event is not defined in mergecraft.enterprise.audit (W22)"
        raise AttributeError(msg)
    return fn


def _require_record_blocking_decision() -> Any:
    fn = getattr(_audit_module(), "record_blocking_decision", None)
    if fn is None:
        msg = "record_blocking_decision is not defined in mergecraft.enterprise.audit (W22)"
        raise AttributeError(msg)
    return fn


def _audit_jsonl_path(root: Path) -> Path:
    return root / DEFAULT_AUDIT_REL


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        payload = json.loads(stripped)
        assert isinstance(payload, dict)
        events.append(payload)
    return events


def _assert_schema(event: dict[str, Any]) -> None:
    missing = _REQUIRED_EVENT_FIELDS - event.keys()
    assert not missing, f"missing required audit fields: {sorted(missing)}"
    assert _IDENTIFIER_FIELDS & event.keys(), "audit event must include run_id and/or artifact_id"
    assert isinstance(event["timestamp"], str)
    assert event["timestamp"]
    assert isinstance(event["event_type"], str)
    assert event["event_type"]
    assert isinstance(event["outcome"], str)
    assert event["outcome"]
    assert isinstance(event["context"], dict)


# --- compatibility pins (pass on baseline before W22) -----------------------


def test_default_audit_rel_points_at_mergecraft_audit_jsonl() -> None:
    """D10: enterprise audit stream lives at ``.mergecraft/audit.jsonl``."""
    assert DEFAULT_AUDIT_REL.as_posix() == ".mergecraft/audit.jsonl"


def test_write_policy_audit_does_not_touch_enterprise_audit_jsonl(tmp_path: Path) -> None:
    """D10: ``policy-audit.json`` is not the enterprise JSONL audit stream."""
    write_policy_audit(tmp_path, rules=[], decisions=[])
    assert (tmp_path / "policy-audit.json").is_file()
    assert not _audit_jsonl_path(tmp_path).exists()


# --- W22 producer API -------------------------------------------------------


@pytest.mark.xfail(reason="green after W22: append_audit_event public API (#417)", strict=False)
def test_append_audit_event_is_exported_public_api() -> None:
    """HK417a: producer entry point is public on ``enterprise.audit``."""
    audit = _audit_module()
    assert "append_audit_event" in audit.__all__
    assert callable(audit.append_audit_event)


@pytest.mark.xfail(reason="green after W22: audit event schema fields (#417)", strict=False)
def test_append_audit_event_writes_required_schema_fields(tmp_path: Path) -> None:
    """HK417b: emitted events carry D10 schema fields."""
    append = _require_append_audit_event()
    append(
        {
            "event_type": "blocking_decision",
            "outcome": "block",
            "run_id": "run-abc",
            "artifact_id": "artifact-1",
            "context": {"reason": "secret in diff"},
        },
        root=tmp_path,
    )
    events = _read_jsonl(_audit_jsonl_path(tmp_path))
    assert len(events) == 1
    _assert_schema(events[0])


@pytest.mark.xfail(
    reason="green after W22: audit JSONL path under workspace root (#417)", strict=False
)
def test_append_audit_event_writes_under_default_audit_rel(tmp_path: Path) -> None:
    """HK417c: producer persists under ``DEFAULT_AUDIT_REL``."""
    append = _require_append_audit_event()
    append(
        {
            "event_type": "run_lifecycle",
            "outcome": "completed",
            "run_id": "run-xyz",
            "context": {"phase": "review"},
        },
        root=tmp_path,
    )
    path = _audit_jsonl_path(tmp_path)
    assert path.is_file()
    assert path.parent.name == ".mergecraft"


@pytest.mark.xfail(reason="green after W22: append-only audit JSONL (#417)", strict=False)
def test_append_audit_event_is_append_only(tmp_path: Path) -> None:
    """HK417d: a second append adds a line instead of truncating the file."""
    append = _require_append_audit_event()
    first = {
        "event_type": "run_lifecycle",
        "outcome": "started",
        "run_id": "run-1",
        "context": {},
    }
    second = {
        "event_type": "blocking_decision",
        "outcome": "block",
        "artifact_id": "artifact-2",
        "context": {"reason": "policy"},
    }
    append(first, root=tmp_path)
    append(second, root=tmp_path)
    events = _read_jsonl(_audit_jsonl_path(tmp_path))
    assert len(events) == 2
    assert events[0]["run_id"] == "run-1"
    assert events[1]["artifact_id"] == "artifact-2"


@pytest.mark.xfail(reason="green after W22: redact secrets in audit context (#417)", strict=False)
def test_append_audit_event_redacts_secrets_in_context(tmp_path: Path) -> None:
    """HK417e: sensitive values in context are redacted before persistence."""
    append = _require_append_audit_event()
    append(
        {
            "event_type": "blocking_decision",
            "outcome": "block",
            "artifact_id": "artifact-secret",
            "context": {"token": _SAMPLE_SECRET, "note": "blocked"},
        },
        root=tmp_path,
    )
    raw = _audit_jsonl_path(tmp_path).read_text(encoding="utf-8")
    assert _SAMPLE_SECRET not in raw
    event = _read_jsonl(_audit_jsonl_path(tmp_path))[0]
    context_blob = json.dumps(event["context"])
    assert _SAMPLE_SECRET not in context_blob


@pytest.mark.xfail(
    reason="green after W22: load_audit_events reads producer output (#417)",
    strict=False,
)
def test_load_audit_events_reads_producer_output(tmp_path: Path) -> None:
    """HK417g: existing reader loads events the producer appends."""
    append = _require_append_audit_event()
    append(
        {
            "event_type": "policy_block",
            "outcome": "block",
            "run_id": "run-policy",
            "context": {"rule_id": "no-secrets"},
        },
        root=tmp_path,
    )
    events = load_audit_events(root=tmp_path)
    assert len(events) == 1
    assert events[0]["event_type"] == "policy_block"
    assert events[0]["run_id"] == "run-policy"


@pytest.mark.xfail(
    reason="green after W22: mergecraft audit export returns producer events (#417)",
    strict=False,
)
def test_audit_export_cli_returns_producer_events(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HK417h: ``mergecraft audit export`` surfaces JSONL written by the producer."""
    append = _require_append_audit_event()
    monkeypatch.chdir(tmp_path)
    append(
        {
            "event_type": "blocking_decision",
            "outcome": "block",
            "artifact_id": "artifact-cli",
            "context": {"reason": "test"},
        },
        root=tmp_path,
    )
    from mergecraft.cli import audit_cmd

    result = runner.invoke(audit_cmd.app, ["export"], env=_DUMB_ENV)
    assert result.exit_code == 0, result.stdout + result.stderr
    payload = json.loads(result.stdout)
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert payload[0]["artifact_id"] == "artifact-cli"


@pytest.mark.xfail(
    reason="green after W22: blocking decision hook emits audit event (#417)",
    strict=False,
)
def test_record_blocking_decision_appends_audit_event(tmp_path: Path) -> None:
    """HK417i: blocking-decision hook appends a structured audit event."""
    record = _require_record_blocking_decision()
    record(
        {
            "decision": "block",
            "reason": "secret in diff",
            "artifact_id": "run-1",
        },
        run_id="run-1",
        root=tmp_path,
    )
    events = load_audit_events(root=tmp_path)
    assert len(events) == 1
    event = events[0]
    _assert_schema(event)
    assert event["event_type"] == "blocking_decision"
    assert event["outcome"] == "block"
    assert event["artifact_id"] == "run-1"


@pytest.mark.xfail(reason="green after W22: audit timestamps are ISO-8601 UTC (#417)", strict=False)
def test_append_audit_event_stamps_utc_timestamp_when_omitted(tmp_path: Path) -> None:
    """HK417j: producer adds a UTC timestamp when the caller omits one."""
    append = _require_append_audit_event()
    before = datetime.now(UTC)
    append(
        {
            "event_type": "run_lifecycle",
            "outcome": "completed",
            "run_id": "run-ts",
            "context": {},
        },
        root=tmp_path,
    )
    after = datetime.now(UTC)
    event = _read_jsonl(_audit_jsonl_path(tmp_path))[0]
    parsed = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    assert before <= parsed <= after


@pytest.mark.xfail(reason="green after W22: reject non-dict audit payloads (#417)", strict=False)
def test_append_audit_event_rejects_non_dict_payload(tmp_path: Path) -> None:
    """HK417k: invalid event payloads fail before touching the JSONL file."""
    append = _require_append_audit_event()
    with pytest.raises((TypeError, ValueError)):
        append("not-a-dict", root=tmp_path)  # type: ignore[arg-type]
    assert not _audit_jsonl_path(tmp_path).exists()
