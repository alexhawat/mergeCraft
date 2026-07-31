"""Regression tests for the Claude Code agent harness (issue #15 / D5)."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import pytest
from loguru import logger

from mergecraft.agents.claude import _run_claude_once
from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.mark.xfail(reason="green after W2: diagnosable claude CLI exit (#15)", strict=False)
def test_claude_exit_with_empty_streams_surfaces_diagnosable_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-zero ``claude`` exit with empty stdout/stderr must name exit code + attempt context."""
    monkeypatch.setenv("CI", "true")

    def _fake_run(
        cmd: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")

    monkeypatch.setattr("mergecraft.agents.claude.subprocess.run", _fake_run)

    log_records: list[tuple[str, str]] = []

    def _capture(record: object) -> None:
        entry = record.record  # type: ignore[attr-defined]
        log_records.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_capture, level="DEBUG")
    try:
        result = _run_claude_once(
            cli="/usr/bin/claude",
            prompt="review this diff",
            ctx=_run_ctx(tmp_path),
            mcp_config=str(tmp_path / "mcp.json"),
        )
    finally:
        logger.remove(sink_id)

    assert result.success is False
    assert result.error is not None
    assert "1" in result.error
    assert result.error != "claude exited 1"

    lowered = result.error.lower()
    assert "model" in lowered or "claude-sonnet" in lowered
    assert "ci" in lowered or "skip-permissions" in lowered or "dangerously" in lowered

    visible = [message for level, message in log_records if level in {"WARNING", "ERROR"}]
    assert visible
    assert any("1" in message or "exit" in message.lower() for message in visible)
