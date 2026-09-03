"""#619 Task 4 — 422 diagnosis, last-resort recovery, and body-length guard.

On PR #619 ``create_pull_request_review`` 422'd three times and the run log
carried no evidence of *why* (a bare ``str(exc)`` drops GitHub's ``errors[]``
array), and the review was simply lost once the targeted recovery paths
(inline-comment demotion, APPROVE -> COMMENT) were exhausted. This suite
pins:

(a) every 422 logs the redacted response body at warning level, naming the
    pull number and the attempted event;
(b) a 422 that neither path can recover from still lands as a bare COMMENT
    review via the last-resort fallback;
(c) an over-long review body is truncated with a visible marker before
    posting, and the truncation is logged.

Uses the same ``RecordingGitHub`` httpx-mocking pattern as
``tests/mcp/test_publication_anchor_recovery.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx
import pytest
from tests.publication_attribution.support import RecordingGitHub, anchor_422_error
from tests.support.tool_context import bind_github_client

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.review import (
    REVIEW_BODY_MAX_CHARS,
    _create_github_review_with_anchor_recovery,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes

if TYPE_CHECKING:
    from pathlib import Path


def _ctx(tmp_path: Path, github: RecordingGitHub) -> ToolContext:
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
    bind_github_client(tool_ctx, github)
    return tool_ctx


def _capture_loguru_warnings() -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="WARNING")
    return captured, sink_id


class _RejectsEventGitHub(RecordingGitHub):
    """422s on any call carrying an ``event`` other than ``COMMENT`` — not a comments-anchor 422."""

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        del owner, repo, pull_number
        self.create_review_calls += 1
        self.review_payloads.append(dict(payload))
        if payload.get("event") != "COMMENT":
            request = httpx.Request("POST", "https://api.github.com/reviews")
            response = httpx.Response(
                422,
                request=request,
                json={
                    "message": "Validation Failed",
                    "errors": [
                        {"resource": "PullRequestReview", "field": "event", "code": "invalid"}
                    ],
                },
            )
            raise httpx.HTTPStatusError("422", request=request, response=response)
        return {
            "id": len(self.review_payloads),
            "node_id": f"n{len(self.review_payloads)}",
            "html_url": f"https://example.test/reviews/{len(self.review_payloads)}",
            "state": "COMMENTED",
        }


@pytest.mark.asyncio
async def test_non_comments_422_lands_as_a_comment_review(tmp_path: Path) -> None:
    """Task 4b — an ``event``-rejection 422 (not a comments-anchor 422) still recovers."""
    github = _RejectsEventGitHub(loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload = {"event": "REQUEST_CHANGES", "body": "Blocking issue found."}

    result, _approve_fallback = await _create_github_review_with_anchor_recovery(
        ctx, pull_number=7, payload=payload
    )

    assert result["state"] == "COMMENTED"
    final = github.review_payloads[-1]
    assert final["event"] == "COMMENT"
    assert "comments" not in final
    assert ctx.tool_state.review_comment_fallback_applied is True


@pytest.mark.asyncio
async def test_422_response_payload_is_logged_with_pull_number_and_event(
    tmp_path: Path,
) -> None:
    """Task 4a — the redacted ``errors[]`` array must reach the log, not just ``str(exc)``."""
    github = RecordingGitHub(comment_422_index=0, loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload = {
        "event": "COMMENT",
        "body": "Body",
        "comments": [{"path": "src/a.py", "line": 1, "body": "Inline."}],
    }
    captured, sink_id = _capture_loguru_warnings()
    try:
        await _create_github_review_with_anchor_recovery(ctx, pull_number=42, payload=payload)
    finally:
        from loguru import logger as loguru_logger

        loguru_logger.remove(sink_id)

    combined = "\n".join(captured)
    assert "42" in combined
    assert "COMMENT" in combined
    # The errors[] array GitHub returns — the evidence a bare str(exc) drops.
    assert "comments" in combined
    assert "invalid" in combined


@pytest.mark.asyncio
async def test_422_payload_logging_redacts_secrets(tmp_path: Path) -> None:
    """The 422 body is redacted like any other tool payload before it hits the log."""

    class _SecretLeakingGitHub(RecordingGitHub):
        async def create_review(
            self, owner: str, repo: str, pull_number: int, **payload: Any
        ) -> dict[str, Any]:
            del owner, repo, pull_number
            self.create_review_calls += 1
            self.review_payloads.append(dict(payload))
            request = httpx.Request("POST", "https://api.github.com/reviews")
            response = httpx.Response(
                422,
                request=request,
                json={
                    "message": "Validation Failed ghp_abcdefghijklmnopqrstuvwxyz012345",
                    "errors": [{"field": "event", "code": "invalid"}],
                },
            )
            raise httpx.HTTPStatusError("422", request=request, response=response)

    github = _SecretLeakingGitHub(loop_guard=20)
    ctx = _ctx(tmp_path, github)
    captured, sink_id = _capture_loguru_warnings()
    try:
        with pytest.raises(httpx.HTTPStatusError):
            await _create_github_review_with_anchor_recovery(
                ctx, pull_number=7, payload={"event": "APPROVE", "body": "Body"}
            )
    finally:
        from loguru import logger as loguru_logger

        loguru_logger.remove(sink_id)

    combined = "\n".join(captured)
    assert "ghp_abcdefghijklmnopqrstuvwxyz012345" not in combined


@pytest.mark.asyncio
async def test_overlong_review_body_is_truncated_before_posting(tmp_path: Path) -> None:
    """Task 4c — GitHub's 65536-character review-body cap is enforced client-side."""
    github = RecordingGitHub(loop_guard=20)
    ctx = _ctx(tmp_path, github)
    huge_body = "x" * (REVIEW_BODY_MAX_CHARS + 5000)
    captured, sink_id = _capture_loguru_warnings()
    try:
        await _create_github_review_with_anchor_recovery(
            ctx, pull_number=7, payload={"event": "COMMENT", "body": huge_body}
        )
    finally:
        from loguru import logger as loguru_logger

        loguru_logger.remove(sink_id)

    posted_body = str(github.review_payloads[-1]["body"])
    assert len(posted_body) <= REVIEW_BODY_MAX_CHARS
    assert "truncated" in posted_body.lower()
    assert ctx.tool_state.review_body_truncated is True
    combined = "\n".join(captured)
    assert "truncat" in combined.lower()


@pytest.mark.asyncio
async def test_body_within_cap_is_not_truncated(tmp_path: Path) -> None:
    """Green guard — a normal-sized body is posted verbatim."""
    github = RecordingGitHub(loop_guard=20)
    ctx = _ctx(tmp_path, github)
    body = "A short review body."
    await _create_github_review_with_anchor_recovery(
        ctx, pull_number=7, payload={"event": "COMMENT", "body": body}
    )
    assert github.review_payloads[-1]["body"] == body
    assert ctx.tool_state.review_body_truncated is False


@pytest.mark.asyncio
async def test_last_resort_fallback_still_raises_when_it_also_422s(tmp_path: Path) -> None:
    """Task 4b — if the COMMENT fallback also 422s, the caller raises (feeds Task 3a)."""

    class _AlwaysRejectingGitHub(RecordingGitHub):
        async def create_review(
            self, owner: str, repo: str, pull_number: int, **payload: Any
        ) -> dict[str, Any]:
            del owner, repo, pull_number
            self.create_review_calls += 1
            self.review_payloads.append(dict(payload))
            raise anchor_422_error(index=None)

    github = _AlwaysRejectingGitHub(loop_guard=20)
    ctx = _ctx(tmp_path, github)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _create_github_review_with_anchor_recovery(
            ctx,
            pull_number=7,
            payload={"event": "APPROVE", "body": "Body"},
        )
    assert exc_info.value.response.status_code == 422
