"""Regression tests for the Claude Code agent harness (issue #15 / D5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from tests.agents.support_claude_stream import write_claude_cli

from mergecraft.agents.claude import _run_claude_once
from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def _run_ctx(
    tmp_path: Path, *, resolved_model: str | None = "anthropic/claude-sonnet-5"
) -> AgentRunContext:
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        resolved_model=resolved_model,
    )


def test_claude_exit_with_empty_streams_surfaces_diagnosable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-zero ``claude`` exit with empty stdout/stderr must name exit code + attempt context."""
    monkeypatch.setenv("CI", "true")

    result = _run_claude_once(
        cli=write_claude_cli(tmp_path, returncode=1),
        prompt="review this diff",
        ctx=_run_ctx(tmp_path),
        mcp_config=str(tmp_path / "mcp.json"),
    )

    assert result.success is False
    assert result.error is not None
    assert "1" in result.error
    assert result.error != "claude exited 1"

    lowered = result.error.lower()
    assert "model" in lowered or "claude-sonnet" in lowered
    assert "ci" in lowered or "skip-permissions" in lowered or "dangerously" in lowered
