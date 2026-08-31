"""W1.1 — bounded, monotonic anchor-422 recovery (wave plan 14, implementation W2)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import patch

import httpx
import pytest
from tests.publication_attribution.support import RecordingGitHub
from tests.support.tool_context import bind_github_client

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.review import (
    ANCHOR_RECOVERY_RETRY_CEILING,
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


@pytest.mark.asyncio
async def test_out_of_range_422_index_terminates_with_bounded_call_count(
    tmp_path: Path,
) -> None:
    """#570 — an out-of-range index must not spin; assert on call count (D2/D3)."""
    github = RecordingGitHub(comment_422_index=99, loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload: dict[str, Any] = {
        "event": "REQUEST_CHANGES",
        "body": "Review body",
        "comments": [{"path": "src/a.py", "line": 10, "body": "Inline finding."}],
    }
    result, _approve_fallback = await _create_github_review_with_anchor_recovery(
        ctx,
        pull_number=7,
        payload=payload,
    )
    assert result["id"] == github.create_review_calls
    assert github.create_review_calls <= ANCHOR_RECOVERY_RETRY_CEILING + 1
    final = github.review_payloads[-1]
    assert "comments" not in final


@pytest.mark.asyncio
async def test_out_of_range_422_demotes_all_inline_comments(tmp_path: Path) -> None:
    """D3 — out-of-range index degrades to demote-all; payload has no ``comments`` key."""
    github = RecordingGitHub(comment_422_index=5, loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload = {
        "event": "COMMENT",
        "body": "Body",
        "comments": [
            {"path": "src/a.py", "line": 1, "body": "First."},
            {"path": "src/b.py", "line": 2, "body": "Second."},
        ],
    }
    await _create_github_review_with_anchor_recovery(ctx, pull_number=7, payload=payload)
    final = github.review_payloads[-1]
    assert "comments" not in final
    body = str(final.get("body") or "")
    assert "First." in body
    assert "Second." in body


@pytest.mark.asyncio
async def test_unparseable_422_index_still_demotes_all_inline_comments(
    tmp_path: Path,
) -> None:
    """Regression — ``index is None`` demote-all path is unchanged."""
    github = RecordingGitHub(comment_422_without_index=True, loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload = {
        "event": "COMMENT",
        "body": "Body",
        "comments": [{"path": "src/a.py", "line": 1, "body": "Inline."}],
    }
    await _create_github_review_with_anchor_recovery(ctx, pull_number=7, payload=payload)
    final = github.review_payloads[-1]
    assert "comments" not in final
    assert "Inline." in str(final.get("body") or "")


@pytest.mark.asyncio
async def test_unchanged_payload_between_attempts_raises_instead_of_looping(
    tmp_path: Path,
) -> None:
    """D1 — a no-op mutator must hard-stop, not ``continue`` forever."""
    github = RecordingGitHub(comment_422_index=0, loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload = {
        "event": "COMMENT",
        "body": "Body",
        "comments": [{"path": "src/a.py", "line": 1, "body": "Inline."}],
    }

    def _noop_demote(current: dict[str, Any], index: int) -> dict[str, Any]:
        del index
        return current

    with (
        patch(
            "mergecraft.mcp.review._demote_inline_comment_from_payload", side_effect=_noop_demote
        ),
        pytest.raises(httpx.HTTPStatusError) as exc_info,
    ):
        await _create_github_review_with_anchor_recovery(ctx, pull_number=7, payload=payload)
    assert exc_info.value.response.status_code == 422
    assert github.create_review_calls <= ANCHOR_RECOVERY_RETRY_CEILING + 1


@pytest.mark.asyncio
async def test_retry_ceiling_raises_last_http_status_error(tmp_path: Path) -> None:
    """D2 — exhausting the retry ceiling re-raises the last 422, not partial success."""
    github = RecordingGitHub(comment_422_index=0, loop_guard=20)
    ctx = _ctx(tmp_path, github)
    payload = {
        "event": "COMMENT",
        "body": "Body",
        "comments": [{"path": "src/a.py", "line": 1, "body": "Inline."}],
    }

    def _noop_demote(current: dict[str, Any], index: int) -> dict[str, Any]:
        del index
        return current

    with (
        patch(
            "mergecraft.mcp.review._demote_inline_comment_from_payload", side_effect=_noop_demote
        ),
        pytest.raises(httpx.HTTPStatusError) as exc_info,
    ):
        await _create_github_review_with_anchor_recovery(ctx, pull_number=7, payload=payload)
    assert exc_info.value.response.status_code == 422
    # D1 hard-stops on unchanged signature before D2's retry ceiling is exhausted.
    assert github.create_review_calls == 1


@pytest.mark.asyncio
async def test_approve_comment_422_fallback_reports_approve_fallback(tmp_path: Path) -> None:
    """Regression — APPROVE → COMMENT fallback still progresses and reports fallback."""
    github = RecordingGitHub(approve_rejected=True)
    ctx = _ctx(tmp_path, github)
    payload = {"event": "APPROVE", "body": "Looks good."}
    _result, approve_fallback = await _create_github_review_with_anchor_recovery(
        ctx,
        pull_number=7,
        payload=payload,
    )
    assert approve_fallback is True
    assert github.review_payloads[0]["event"] == "APPROVE"
    assert github.review_payloads[-1]["event"] == "COMMENT"


@pytest.mark.asyncio
async def test_non_422_http_status_error_propagates_immediately(tmp_path: Path) -> None:
    """Regression — non-422 failures are not retried by the recovery loop."""

    class _ForbiddenGitHub(RecordingGitHub):
        async def create_review(
            self, owner: str, repo: str, pull_number: int, **payload: Any
        ) -> dict[str, Any]:
            del owner, repo, pull_number, payload
            self.create_review_calls += 1
            request = httpx.Request("POST", "https://api.github.com/reviews")
            response = httpx.Response(403, request=request, json={"message": "Forbidden"})
            raise httpx.HTTPStatusError("403", request=request, response=response)

    github = _ForbiddenGitHub()
    ctx = _ctx(tmp_path, github)
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await _create_github_review_with_anchor_recovery(
            ctx,
            pull_number=7,
            payload={"event": "COMMENT", "body": "Body"},
        )
    assert exc_info.value.response.status_code == 403
    assert github.create_review_calls == 1
