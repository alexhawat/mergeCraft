"""W1.6 — inline anchor pre-validation and 422 recovery (#530, implementation W6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from loguru import logger

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.support.tool_context import bind_review_publication_scope, github_client_from_ctx

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingGitHub(GitHubClient):
    def __init__(
        self, *, reject_all_comments: bool = False, approve_rejected: bool = False
    ) -> None:
        super().__init__(token="test-token")
        self.review_payload: dict[str, Any] = {}
        self.review_payloads: list[dict[str, Any]] = []
        self.reject_all_comments = reject_all_comments
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
        if self.reject_all_comments and payload.get("comments"):
            request = httpx.Request("POST", "https://api.github.com/reviews")
            response = httpx.Response(
                422,
                request=request,
                json={
                    "message": "Validation Failed",
                    "errors": [{"field": "comments", "code": "invalid"}],
                },
            )
            raise httpx.HTTPStatusError("422", request=request, response=response)
        return {
            "id": 1,
            "node_id": "n1",
            "html_url": "https://x/1",
            "state": payload.get("event", "COMMENTED"),
        }


def _ctx(tmp_path: Path, github: _RecordingGitHub) -> ToolContext:
    tool_ctx = ToolContext(
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
    bind_review_publication_scope(tool_ctx)
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(
        "diff --git a/src/in_diff.py b/src/in_diff.py\n@@ -8,3 +8,4 @@\n context\n+added\n",
        encoding="utf-8",
    )
    primary_repo_state(tool_ctx.tool_state).diff_path = str(diff_path)
    return tool_ctx


@pytest.mark.asyncio
async def test_out_of_diff_inline_comment_is_dropped_before_post(
    tmp_path: Path,
) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github)
    warnings: list[str] = []
    handler_id = logger.add(lambda msg: warnings.append(msg.record["message"]), level="WARNING")
    try:
        spec = create_pull_request_review_tool(ctx)
        await spec.execute(
            {
                "pull_number": 7,
                "body": "Review body",
                "comments": [{"path": "src/off_diff.py", "line": 999, "body": "Outside diff."}],
            }
        )
    finally:
        logger.remove(handler_id)
    payload = github_client_from_ctx(ctx).review_payload  # type: ignore[attr-defined]
    comments = list(payload.get("comments") or [])
    assert comments == []
    assert warnings, "dropping an invalid anchor must be logged"


@pytest.mark.asyncio
async def test_request_changes_422_does_not_propagate_to_agent(tmp_path: Path) -> None:
    github = _RecordingGitHub(reject_all_comments=True)
    ctx = _ctx(tmp_path, github)
    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute(
        {
            "pull_number": 7,
            "body": "Please fix.",
            "approved": False,
            "request_changes": True,
            "comments": [{"path": "src/in_diff.py", "line": 10, "body": "Bug."}],
        }
    )
    assert result.is_error is False


@pytest.mark.asyncio
async def test_all_anchors_rejected_still_posts_body_and_verdict(tmp_path: Path) -> None:
    github = _RecordingGitHub(reject_all_comments=True)
    ctx = _ctx(tmp_path, github)
    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": "Verdict body must survive.",
            "approved": False,
            "request_changes": True,
            "comments": [{"path": "src/in_diff.py", "line": 10, "body": "Bug."}],
        }
    )
    assert github.review_payloads
    final = github.review_payloads[-1]
    assert final.get("body")
    assert final.get("event") == "REQUEST_CHANGES"
    assert not final.get("comments")


@pytest.mark.asyncio
async def test_approve_comment_422_fallback_still_works(tmp_path: Path) -> None:
    github = _RecordingGitHub(approve_rejected=True)
    ctx = _ctx(tmp_path, github)
    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute({"pull_number": 7, "body": "Looks good.", "approved": True})
    assert result.is_error is False
    assert github.review_payloads[0]["event"] == "APPROVE"
    assert github.review_payloads[1]["event"] == "COMMENT"
    assert ctx.tool_state.approval is not None
    assert ctx.tool_state.approval.would_approve is True
