"""Finding-stream boundary: CLI protocol vs offline vs MCP ``set_output``."""

from __future__ import annotations

import json
from io import StringIO
from types import SimpleNamespace
from typing import Any

import mergecraft.offline_review as offline_mod
from mergecraft.analyzers.finding import make_finding
from mergecraft.cli.agent_protocol import AgentProtocolStream, notify_findings
from mergecraft.cli.diff_review_cmd import _finish_agent_protocol
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


def test_finish_agent_protocol_re_emits_batch_short_ids_for_seen_findings() -> None:
    """Edge: finish-path notify refreshes streamed rows with batch-resolved short ids."""
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
    notify_findings(stream.finding, [row], seen=seen)
    _finish_agent_protocol(
        stream,
        outcome=RunOutcome.passed,
        exit_code=0,
        findings=[finding],
        seen=seen,
    )
    events = [line for line in buf.getvalue().splitlines() if line.strip()]
    finding_events = [
        line for line in events if '"event": "finding"' in line or '"event":"finding"' in line
    ]
    assert len(finding_events) == 2
    final = json.loads(finding_events[-1])["finding"]
    assert isinstance(final.get("short_id"), str)
    assert final["short_id"].startswith("MC-")


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
