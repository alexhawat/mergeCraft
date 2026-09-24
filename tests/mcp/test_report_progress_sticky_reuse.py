"""``report_progress`` must reuse the PR's existing sticky on a later run.

At the start of a fresh Action run ``progress_comment`` is ``None``. The tool
looked up the sticky only to hydrate the ledger, threw the id away, and posted
a second comment. It must look the trusted sticky up, update it, and pin
``ProgressComment`` — while a deliberately deleted comment stays deleted, the
plan-comment target is unchanged, and a lookup failure still creates without
raising out of the tool.
"""

from __future__ import annotations

import json
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
_STICKY_ID = 55
_PLAN_COMMENT_ID = 42


class _FakeScm:
    def __init__(self, *, fail_lookup: bool = False) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self.creates = 0
        self.updates = 0
        self.updated_ids: list[int] = []
        self.fail_lookup = fail_lookup
        self._next_id = 100

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if self.fail_lookup:
            raise RuntimeError("issue-comment lookup unavailable")
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
        self.creates += 1
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
        self.updates += 1
        self.updated_ids.append(int(comment_id))
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


def _bot_sticky_body() -> str:
    fingerprint = finding_fingerprint(path="src/app.py", body="Missing timeout.")
    book = ledger.FindingLedger()
    book.record(fingerprint, "open", source="inline", round_index=1)
    return f"## mergeCraft progress\n\nRound one.\n\n{book.render_ledger_block()}\n"


def _action(result: Any) -> str:
    payload = json.loads(result.content[0]["text"])
    return str(payload["action"])


@pytest.mark.asyncio
async def test_second_run_first_call_reuses_the_existing_sticky(tmp_path: Path) -> None:
    scm = _FakeScm()
    scm.comments[_STICKY_ID] = {
        "id": _STICKY_ID,
        "body": _bot_sticky_body(),
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    ctx = _ctx(tmp_path, scm)
    assert ctx.tool_state.progress_comment is None

    result = await report_progress_tool(ctx).execute({"body": "Round two."})

    assert result.is_error is False
    assert _action(result) == "updated"
    assert scm.creates == 0, "a later run must not post a second sticky"
    assert scm.updated_ids == [_STICKY_ID]
    progress = ctx.tool_state.progress_comment
    assert isinstance(progress, ProgressComment)
    assert progress.id == str(_STICKY_ID)
    assert "Round two." in scm.comments[_STICKY_ID]["body"]


@pytest.mark.asyncio
async def test_deleted_progress_comment_still_skips(tmp_path: Path) -> None:
    scm = _FakeScm()
    scm.comments[_STICKY_ID] = {
        "id": _STICKY_ID,
        "body": _bot_sticky_body(),
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    ctx = _ctx(tmp_path, scm)
    ctx.tool_state.progress_comment = False

    result = await report_progress_tool(ctx).execute({"body": "Round two."})

    assert result.is_error is False
    assert _action(result) == "skipped"
    assert scm.creates == 0
    assert scm.updates == 0
    assert ctx.tool_state.progress_comment is False


@pytest.mark.asyncio
async def test_target_plan_comment_is_unchanged(tmp_path: Path) -> None:
    scm = _FakeScm()
    scm.comments[_PLAN_COMMENT_ID] = {
        "id": _PLAN_COMMENT_ID,
        "body": "## Plan\n\nOriginal plan body.",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    ctx = _ctx(tmp_path, scm)
    ctx.tool_state.existing_plan_comment_id = _PLAN_COMMENT_ID

    result = await report_progress_tool(ctx).execute(
        {"body": "Plan progress.", "target_plan_comment": True}
    )

    assert result.is_error is False
    assert _action(result) == "updated"
    assert scm.updated_ids == [_PLAN_COMMENT_ID]
    assert scm.creates == 0
    assert ctx.tool_state.progress_comment is None


@pytest.mark.asyncio
async def test_lookup_failure_creates_and_does_not_raise(tmp_path: Path) -> None:
    scm = _FakeScm(fail_lookup=True)
    ctx = _ctx(tmp_path, scm)

    result = await report_progress_tool(ctx).execute({"body": "Round two."})

    assert result.is_error is False, "a lookup failure must not surface as a tool error"
    assert _action(result) == "created"
    assert scm.creates == 1
    progress = ctx.tool_state.progress_comment
    assert isinstance(progress, ProgressComment)
