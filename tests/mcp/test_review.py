"""Tests for create_pull_request_review inline-comment assembly."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import FINDING_MARKER_PREFIX, finding_fingerprint
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingGitHub(GitHubClient):
    """GitHub client that captures the review payload instead of sending it."""

    def __init__(self, *, approve_rejected: bool = False) -> None:
        super().__init__(token="test-token")
        self.review_payload: dict[str, Any] = {}
        self.review_payloads: list[dict[str, Any]] = []
        self.approve_rejected = approve_rejected

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payload = payload
        self.review_payloads.append(payload)
        if self.approve_rejected and payload.get("event") == "APPROVE":
            request = httpx.Request("POST", "https://api.github.com/reviews")
            response = httpx.Response(422, request=request, json={"message": "Unprocessable"})
            raise httpx.HTTPStatusError("422", request=request, response=response)
        return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=_RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


async def _submit(ctx: ToolContext, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spec = create_pull_request_review_tool(ctx)
    await spec.execute({"pull_number": 7, "body": "review body", "comments": comments})
    payload = ctx.github.review_payload  # type: ignore[attr-defined]
    return list(payload.get("comments") or [])


@pytest.mark.asyncio
async def test_inline_comments_are_fingerprinted(ctx: ToolContext) -> None:
    inline = await _submit(ctx, [{"path": "src/app.py", "line": 12, "body": "A finding."}])
    expected = finding_fingerprint(path="src/app.py", body="A finding.")
    assert inline[0]["body"].startswith("A finding.")
    assert f"{FINDING_MARKER_PREFIX}{expected} -->" in inline[0]["body"]


@pytest.mark.asyncio
async def test_identical_findings_share_a_fingerprint(ctx: ToolContext) -> None:
    inline = await _submit(
        ctx,
        [
            {"path": "src/app.py", "line": 12, "body": "A finding."},
            {"path": "src/app.py", "line": 40, "body": "A  finding."},
            {"path": "src/other.py", "line": 12, "body": "A finding."},
        ],
    )
    first, reworded, other_path = (c["body"] for c in inline)
    marker = f"{FINDING_MARKER_PREFIX}{finding_fingerprint(path='src/app.py', body='A finding.')}"
    assert marker in first
    assert marker in reworded
    assert marker not in other_path


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_approve_422_falls_back_to_comment_and_keeps_approval(tmp_path: Path) -> None:
    github = _RecordingGitHub(approve_rejected=True)
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        pr_approve_enabled=True,
    )
    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )
    assert result.is_error is False
    payload_text = result.content[0]["text"]
    assert "approveFallbackDueTo422" in payload_text
    assert github.review_payloads[0]["event"] == "APPROVE"
    assert github.review_payloads[1]["event"] == "COMMENT"
    assert ctx.tool_state.approval is not None
    assert ctx.tool_state.approval.would_approve is True


async def test_suggestion_is_fenced_before_fingerprinting(ctx: ToolContext) -> None:
    inline = await _submit(
        ctx,
        [{"path": "src/app.py", "line": 12, "body": "Parenthesize.", "suggestion": "    pass"}],
    )
    body = inline[0]["body"]
    assert "```suggestion\n    pass\n```" in body
    assert body.index("```suggestion") < body.index(FINDING_MARKER_PREFIX)
