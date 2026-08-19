"""RH4 — ordered block replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.provider_harness.blocks import replay_blocks
from tests.support.provider_harness.schema import ResponseBlock

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
    from mergecraft.mcp.tool_state import init_tool_state
    from mergecraft.modes import compute_modes
    from mergecraft.utils.github import GitHubClient

    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
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
        pr_approve_enabled=True,
    )


def test_text_before_terminal_tool_call_is_replayed(ctx) -> None:
    blocks = [
        ResponseBlock(kind="text", text="thinking"),
        ResponseBlock(
            kind="tool_call",
            tool_name="submit_review_verdict",
            arguments={"verdict": "approve", "summary": "ok", "findings": []},
        ),
    ]
    result = replay_blocks(blocks, ctx=ctx)
    assert result.output == "thinking"
    assert result.terminal_submission_received is True


def test_terminal_tool_call_before_text_is_replayed(ctx) -> None:
    blocks = [
        ResponseBlock(
            kind="tool_call",
            tool_name="submit_review_verdict",
            arguments={"verdict": "approve", "summary": "ok", "findings": []},
        ),
        ResponseBlock(kind="text", text="after"),
    ]
    result = replay_blocks(blocks, ctx=ctx)
    assert result.terminal_submission_received is True
    assert "after" in (result.output or "")


def test_multiple_tool_calls_preserve_order(ctx) -> None:
    blocks = [
        ResponseBlock(kind="tool_call", tool_name="other_tool", tool_call_id="a", arguments={}),
        ResponseBlock(
            kind="tool_call",
            tool_name="submit_review_verdict",
            arguments={"verdict": "approve", "summary": "ok", "findings": []},
        ),
    ]
    result = replay_blocks(blocks, ctx=ctx)
    assert result.terminal_submission_received is True


def test_malformed_tool_arguments_are_visible_to_validation(ctx) -> None:
    blocks = [
        ResponseBlock(
            kind="tool_call",
            tool_name="submit_review_verdict",
            arguments={"verdict": "approve"},
        ),
    ]
    result = replay_blocks(blocks, ctx=ctx)
    assert result.success is False
    assert result.error
