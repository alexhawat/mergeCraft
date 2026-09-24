"""``report_progress`` must snapshot the pre-footer body it posted.

``last_progress_body`` is the base the deterministic record writer rebuilds the
sticky from. When ``report_progress`` stores the raw agent argument instead of
the body it actually posted (learnings delta + hydrated ledger, footer aside),
the record writer has no ledger to keep and the cross-round memory is lost.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.findings import ledger
from mergecraft.mcp.comment import report_progress_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ProgressComment, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

_PR_NUMBER = 7
_RAW_BODY = "Reviewing the diff."
_LEARNINGS_DELTA = "### Learnings delta"
_FOOTER_MARKER = "*via mergecraft*"


class _FakeScm:
    def __init__(self) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self._next_id = 100

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        page = int((params or {}).get("page", 1))
        if page != 1:
            return []
        return [dict(row) for row in self.comments.values()]

    async def get_issue_comment(self, owner: str, repo: str, comment_id: int) -> dict[str, Any]:
        return dict(self.comments[int(comment_id)])

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        self._next_id += 1
        row = {
            "id": self._next_id,
            "body": body,
            "user": {"login": "github-actions[bot]", "type": "Bot"},
        }
        self.comments[self._next_id] = row
        return dict(row)

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        row = self.comments[int(comment_id)]
        row["body"] = body
        return dict(row)


def _ctx(tmp_path: Path, scm: _FakeScm) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = _PR_NUMBER
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=_PR_NUMBER, is_pr=True),
        ),
        scm=scm,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _seed_delta_and_ledger(ctx: ToolContext, tmp_path: Path) -> str:
    path = tmp_path / "mergecraft-learnings.md"
    path.write_text("# Learnings\n\n- Pin the action SHA.\n", encoding="utf-8")
    ctx.tool_state.learnings_file_path = str(path)
    ctx.tool_state.learnings_seed = "# Learnings\n"

    fingerprint = finding_fingerprint(path="src/app.py", body="Missing timeout.")
    ledger.ensure_finding_ledger(ctx.tool_state).record(
        fingerprint,
        "open",
        source="inline",
        round_index=1,
    )
    return fingerprint


def _posted_body(scm: _FakeScm, ctx: ToolContext) -> str:
    progress = ctx.tool_state.progress_comment
    assert isinstance(progress, ProgressComment)
    return str(scm.comments[int(progress.id)]["body"])


def _assert_snapshot_is_pre_footer(stored: str | None, posted: str) -> None:
    assert stored is not None
    assert stored != _RAW_BODY, "the raw agent argument is not what was posted"
    assert _FOOTER_MARKER not in stored, "the snapshot must exclude the footer"
    assert posted.startswith(stored.rstrip()), (
        f"the posted body must be the snapshot plus the footer:\n{posted!r}\n{stored!r}"
    )
    assert _LEARNINGS_DELTA in stored, "the snapshot keeps the learnings delta"


@pytest.mark.xfail(
    reason="green after LG2: report_progress stores the body it posted",
    strict=False,
)
@pytest.mark.asyncio
async def test_first_call_stores_the_pre_footer_body(tmp_path: Path) -> None:
    scm = _FakeScm()
    ctx = _ctx(tmp_path, scm)
    fingerprint = _seed_delta_and_ledger(ctx, tmp_path)

    result = await report_progress_tool(ctx).execute({"body": _RAW_BODY})

    assert result.is_error is False
    posted = _posted_body(scm, ctx)
    stored = ctx.tool_state.last_progress_body
    _assert_snapshot_is_pre_footer(stored, posted)
    assert stored is not None
    assert fingerprint in stored, "the hydrated ledger must be part of the snapshot"


@pytest.mark.xfail(
    reason="green after LG2: report_progress stores the body it posted",
    strict=False,
)
@pytest.mark.asyncio
async def test_update_call_stores_the_pre_footer_body(tmp_path: Path) -> None:
    """The in-place update branch snapshots its body the same way the create branch does."""
    scm = _FakeScm()
    ctx = _ctx(tmp_path, scm)
    _seed_delta_and_ledger(ctx, tmp_path)

    first = await report_progress_tool(ctx).execute({"body": _RAW_BODY})
    assert first.is_error is False
    assert isinstance(ctx.tool_state.progress_comment, ProgressComment)
    comment_id = ctx.tool_state.progress_comment.id

    second = await report_progress_tool(ctx).execute({"body": "Second update."})
    assert second.is_error is False
    assert isinstance(ctx.tool_state.progress_comment, ProgressComment)
    assert ctx.tool_state.progress_comment.id == comment_id

    posted = _posted_body(scm, ctx)
    stored = ctx.tool_state.last_progress_body
    _assert_snapshot_is_pre_footer(stored, posted)
    assert "Second update." in posted
