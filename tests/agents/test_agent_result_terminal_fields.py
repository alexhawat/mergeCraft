"""AgentResult fields that record whether a terminal verdict was submitted (VP1 / V2).

``test_defaults_preserve_existing_behaviour`` is a V2 regression pin.
``test_fields_populate_from_tool_state`` was xfail until VP1.2; the marker
was removed after that wave populated the fields from ``ctx.tool_state``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _tool_ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def test_defaults_preserve_existing_behaviour() -> None:
    """V2 regression pin: existing ``AgentResult`` constructions still work."""
    result = AgentResult(success=True)
    assert result.success is True
    assert result.output is None
    assert result.error is None
    assert result.metadata == {}
    assert result.usage is None
    assert getattr(result, "terminal_submission_received", False) is False
    assert getattr(result, "terminal_submission_id", None) is None

    populated = AgentResult(success=True, output="done", metadata={"k": "v"})
    assert populated.output == "done"
    assert populated.metadata == {"k": "v"}
    assert getattr(populated, "terminal_submission_received", False) is False


@pytest.mark.asyncio
async def test_fields_populate_from_tool_state(tmp_path: Path) -> None:
    """After a recorded submission, finalize copies the flag and id onto ``AgentResult``."""
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    tool_ctx = _tool_ctx(tmp_path)
    recorded = await submit_review_verdict_tool(tool_ctx).execute(
        {
            "verdict": "approve",
            "summary": "No blocking issues in the diff.",
            "findings": [],
        }
    )
    assert recorded.is_error is False
    submission = tool_ctx.tool_state.terminal_submission
    assert submission is not None
    submission_id = submission.id

    run_ctx = AgentRunContext(
        payload=tool_ctx.payload,
        mcp_server_url=tool_ctx.mcp_server_url,
        tmpdir=tool_ctx.tmpdir,
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(),
        tool_state=tool_ctx.tool_state,
    )
    finalized = await finalize_agent_result(run_ctx, AgentResult(success=True))
    assert finalized.terminal_submission_received is True
    assert finalized.terminal_submission_id == submission_id
    diagnostics: dict[str, Any] = finalized.diagnostics
    assert isinstance(diagnostics, dict)
    assert diagnostics.get("attempt_id") == submission.attempt_id
