"""Malformed draft rows must not block ``submit_review_verdict``."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.mcp.verdict import establish_offline_review_scope, submit_review_verdict_tool
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def _ctx(tmp_path) -> ToolContext:
    tool_state = init_tool_state(owner="local", name="demo", dir=str(tmp_path))
    establish_offline_review_scope(tool_state, diff_path=str(tmp_path / "x.diff"))
    (tmp_path / "x.diff").write_text("diff\n", encoding="utf-8")
    return ToolContext(
        agent_id="opencode",
        repo=RepoIdentity(owner="local", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown"), shell="disabled"),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("opencode"),
        tool_state=tool_state,
        mcp_server_url="http://127.0.0.1:9/mcp/reviewer",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


@pytest.mark.asyncio
async def test_submit_drops_malformed_findings_and_records_verdict(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    ctx.tool_state.agent_findings.append(
        {
            "confidence": "high",
            "severity": "Major",
            "title": "bad",
            "message": "missing path",
        }
    )
    payload: dict[str, Any] = {
        "verdict": "approve",
        "summary": "Clean diff.",
        "findings": [
            {
                "confidence": "high",
                "severity": "Major",
                "title": "also bad",
            },
            {
                "path": "src/a.py",
                "body": "valid finding",
                "severity": "Minor",
                "line": 3,
            },
        ],
    }
    result = await submit_review_verdict_tool(ctx).execute(payload)
    assert result.is_error is False
    assert ctx.tool_state.terminal_submission is not None
    assert ctx.tool_state.terminal_submission.verdict == "approve"
