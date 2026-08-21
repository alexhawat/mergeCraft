"""Finding-stream boundary: CLI protocol vs offline vs MCP ``set_output``."""

from __future__ import annotations

import ast
import inspect
from io import StringIO
from types import SimpleNamespace
from typing import Any

from mergecraft.analyzers.finding import make_finding
from mergecraft.cli.agent_protocol import AgentProtocolStream, notify_findings
from mergecraft.cli.diff_review_cmd import _finish_agent_protocol
from mergecraft.mcp.output import _notify_set_output_findings
from mergecraft.run_outcome import RunOutcome


def _offline_source() -> str:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    return (root / "src" / "mergecraft" / "offline_review.py").read_text(encoding="utf-8")


def test_offline_review_does_not_import_agent_protocol_or_notify_findings() -> None:
    """Unit: streaming stays at the CLI boundary; offline_review does not import it."""
    source = _offline_source()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        module = ""
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
        elif isinstance(node, ast.Import):
            module = ",".join(alias.name for alias in node.names)
        if "agent_protocol" in module:
            raise AssertionError(f"offline_review imports agent_protocol: {module}")
        if isinstance(node, ast.ImportFrom):
            names = {alias.name for alias in node.names}
            assert "notify_findings" not in names
    assert "notify_findings" not in source
    assert "mergecraft.cli.agent_protocol" not in source


def test_diff_review_cmd_uses_notify_findings_once_policy() -> None:
    """Happy: CLI review streams via ``notify_findings`` (dedupe / once-per-row)."""
    from mergecraft.cli import diff_review_cmd

    source = inspect.getsource(diff_review_cmd)
    assert "notify_findings" in source
    assert "seen=seen" in source
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


def test_finish_agent_protocol_does_not_redeliver_already_seen_finding() -> None:
    """Edge: finish-path notify shares ``seen`` so a live finding is not emitted twice."""
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
    assert len(finding_events) == 1


def test_mcp_set_output_notifies_on_finding_per_row_without_cli_import() -> None:
    """Integration: MCP ``set_output`` calls ``tool_state.on_finding`` per row, no CLI import."""
    import mergecraft.mcp.output as output_mod

    source = inspect.getsource(output_mod)
    assert "tool_state.on_finding" in source
    assert "mergecraft.cli" not in source
    rows: list[dict[str, Any]] = []
    ctx = SimpleNamespace(tool_state=SimpleNamespace(on_finding=rows.append))
    _notify_set_output_findings(
        ctx,  # type: ignore[arg-type]
        {"findings": [{"rule_id": "a"}, {"rule_id": "b"}]},
    )
    assert [row["rule_id"] for row in rows] == ["a", "b"]
