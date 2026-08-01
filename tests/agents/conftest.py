"""Shared fixtures for agent harness contract tests (Batch D / W11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, ResolvedPayload
from mergecraft.mcp.tool_state import init_tool_state

if TYPE_CHECKING:
    from pathlib import Path


def make_agent_run_context(
    tmp_path: Path,
    *,
    resolved_model: str | None,
) -> AgentRunContext:
    """Build a minimal ``AgentRunContext`` for harness contract tests."""
    return AgentRunContext(
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        mcp_server_url="http://127.0.0.1:0/mcp",
        tmpdir=str(tmp_path),
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(user="review this diff"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        resolved_model=resolved_model,
    )
