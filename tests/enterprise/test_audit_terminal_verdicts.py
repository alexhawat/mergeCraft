"""Enterprise audit records every terminal non-approve verdict (#417)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from mergecraft.enterprise.audit import load_audit_events, maybe_audit_blocking_terminal_submission
from mergecraft.mcp.tool_state import TerminalSubmission, init_tool_state


def test_maybe_audit_records_request_changes(tmp_path: Path) -> None:
    recorded = TerminalSubmission(
        id="artifact-rc",
        verdict="request_changes",
        summary="please fix tests",
        findings=[],
        payload_hash="hash",
        submitted_at="2026-01-01T00:00:00+00:00",
        attempt_id=1,
    )
    ctx = SimpleNamespace(tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)))

    maybe_audit_blocking_terminal_submission(ctx, recorded)  # type: ignore[arg-type]

    events = load_audit_events(root=tmp_path)
    assert len(events) == 1
    assert events[0]["event_type"] == "terminal_verdict"
    assert events[0]["outcome"] == "request_changes"
    assert events[0]["artifact_id"] == "artifact-rc"


def test_maybe_audit_skips_approve(tmp_path: Path) -> None:
    recorded = TerminalSubmission(
        id="artifact-ok",
        verdict="approve",
        summary="lgtm",
        findings=[],
        payload_hash="hash",
        submitted_at="2026-01-01T00:00:00+00:00",
        attempt_id=1,
    )
    ctx = SimpleNamespace(tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)))

    maybe_audit_blocking_terminal_submission(ctx, recorded)  # type: ignore[arg-type]

    assert load_audit_events(root=tmp_path) == []
