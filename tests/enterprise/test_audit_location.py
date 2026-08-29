"""BR1.6 / BR7 — enterprise audit log location (MCB-21, D13)."""

from __future__ import annotations

from pathlib import Path


def _sample_event() -> dict[str, object]:
    return {
        "event_type": "terminal_verdict",
        "outcome": "request_changes",
        "artifact_id": "br1-audit-location-canary",
        "context": {"summary": "audit location contract"},
    }


def test_audit_log_is_not_inside_the_workspace(tmp_path: Path) -> None:
    """MCB-21: default audit persistence must not live under the agent workspace."""
    from mergecraft.enterprise.audit import append_audit_event, load_audit_events

    workspace = tmp_path / "repo"
    workspace.mkdir()
    append_audit_event(_sample_event(), root=workspace)
    inside = workspace / ".mergecraft" / "audit.jsonl"
    events = load_audit_events(root=workspace)
    assert events
    assert not inside.is_file()


def test_audit_root_env_override_is_honoured(tmp_path: Path, monkeypatch) -> None:
    """MCB-21: ``MERGECRAFT_AUDIT_ROOT`` selects the audit sink directory."""
    from mergecraft.enterprise.audit import append_audit_event, load_audit_events

    workspace = tmp_path / "repo"
    workspace.mkdir()
    audit_root = tmp_path / "external-audit"
    audit_root.mkdir()
    monkeypatch.setenv("MERGECRAFT_AUDIT_ROOT", str(audit_root))
    append_audit_event(_sample_event(), root=workspace)
    expected = audit_root / "audit.jsonl"
    assert expected.is_file()
    events = load_audit_events(root=workspace)
    assert events[0]["artifact_id"] == "br1-audit-location-canary"
