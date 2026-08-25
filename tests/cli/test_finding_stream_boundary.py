"""Finding-stream boundary: CLI protocol vs offline vs MCP ``set_output``."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from typing import Any

import mergecraft.offline_review as offline_mod
from mergecraft.analyzers.finding import make_finding
from mergecraft.cli.agent_protocol import AgentProtocolStream, notify_findings
from mergecraft.cli.diff_review_cmd import _agent_finding_record, _finish_agent_protocol
from mergecraft.mcp.output import _notify_set_output_findings
from mergecraft.run_outcome import RunOutcome


def test_offline_review_does_not_import_agent_protocol_or_notify_findings() -> None:
    """Unit: streaming stays at the CLI boundary; offline_review does not export it."""
    assert not hasattr(offline_mod, "notify_findings")
    assert not hasattr(offline_mod, "AgentProtocolStream")
    assert "agent_protocol" not in offline_mod.__dict__


def test_diff_review_cmd_uses_notify_findings_once_policy() -> None:
    """Happy: CLI review streams via ``notify_findings`` (dedupe / once-per-row)."""
    from mergecraft.cli import diff_review_cmd

    assert diff_review_cmd.notify_findings is notify_findings
    emitted: list[dict[str, Any]] = []
    finding = {
        "rule_id": "ONCE-1",
        "path": "demo.py",
        "start_line": 1,
        "message": "dup",
    }
    seen: set[str] = set()
    notify_findings(emitted.append, [finding, finding], seen=seen)
    notify_findings(emitted.append, [finding], seen=seen)
    assert len(emitted) == 1


def test_finish_agent_protocol_re_emits_only_when_batch_short_id_changes() -> None:
    """Edge: finish-path refresh upgrades short ids without duplicating unchanged rows."""
    buf = StringIO()
    stream = AgentProtocolStream(stream=buf)
    finding = make_finding(
        tool="mergecraft-agent",
        rule_id="ONCE-2",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="streamed once",
        path="demo.py",
        start_line=1,
        end_line=1,
        source="agent",
    )
    row = finding.model_dump()
    seen: set[str] = set()
    streamed_short_ids: dict[str, str] = {}
    notify_findings(
        stream.finding,
        [_agent_finding_record(row)],
        seen=seen,
        streamed_short_ids=streamed_short_ids,
    )
    _finish_agent_protocol(
        stream,
        outcome=RunOutcome.passed,
        exit_code=0,
        findings=[finding],
        seen=seen,
        streamed_short_ids=streamed_short_ids,
    )
    events = [line for line in buf.getvalue().splitlines() if line.strip()]
    finding_events = [
        line for line in events if '"event": "finding"' in line or '"event":"finding"' in line
    ]
    assert len(finding_events) == 1
    payload = json.loads(finding_events[0])["finding"]
    assert isinstance(payload.get("short_id"), str)
    assert payload["short_id"].startswith("MC-")


def test_finish_agent_protocol_refreshes_colliding_short_ids() -> None:
    """Edge: batch collision resolution re-emits only rows whose short id changed."""
    buf = StringIO()
    stream = AgentProtocolStream(stream=buf)
    fp1 = "a83f91c2d4e5f6a7b8c9d0e1f2a3b4c5"
    fp2 = "a83f91d3e4f5a6b7c8d9e0f1a2b3c4d6"
    findings = [
        make_finding(
            tool="mergecraft-agent",
            rule_id="COLLIDE-1",
            category="Maintainability & Code Quality",
            severity="Minor",
            confidence="likely",
            message="first",
            path="a.py",
            start_line=1,
            end_line=1,
            source="agent",
            fingerprint=fp1,
        ),
        make_finding(
            tool="mergecraft-agent",
            rule_id="COLLIDE-2",
            category="Maintainability & Code Quality",
            severity="Minor",
            confidence="likely",
            message="second",
            path="b.py",
            start_line=1,
            end_line=1,
            source="agent",
            fingerprint=fp2,
        ),
    ]
    seen: set[str] = set()
    streamed_short_ids: dict[str, str] = {}
    for finding in findings:
        notify_findings(
            stream.finding,
            [_agent_finding_record(finding.model_dump())],
            seen=seen,
            streamed_short_ids=streamed_short_ids,
        )
    _finish_agent_protocol(
        stream,
        outcome=RunOutcome.passed,
        exit_code=0,
        findings=findings,
        seen=seen,
        streamed_short_ids=streamed_short_ids,
    )
    events = [line for line in buf.getvalue().splitlines() if line.strip()]
    finding_events = [
        line for line in events if '"event": "finding"' in line or '"event":"finding"' in line
    ]
    assert len(finding_events) == 3
    final = json.loads(finding_events[-1])["finding"]
    assert final["fingerprint"] == fp2
    assert final["short_id"] == "MC-a83f91d"


def test_mcp_set_output_notifies_on_finding_per_row_without_cli_import() -> None:
    """Integration: MCP ``set_output`` calls ``tool_state.on_finding`` per row, no CLI import."""
    import mergecraft.mcp.output as output_mod

    assert not any(
        isinstance(value, str) and value.startswith("mergecraft.cli")
        for value in output_mod.__dict__.values()
    )
    rows: list[dict[str, Any]] = []
    ctx = SimpleNamespace(tool_state=SimpleNamespace(on_finding=rows.append))
    _notify_set_output_findings(
        ctx,  # type: ignore[arg-type]
        {"findings": [{"rule_id": "a"}, {"rule_id": "b"}]},
    )
    assert [row["rule_id"] for row in rows] == ["a", "b"]
