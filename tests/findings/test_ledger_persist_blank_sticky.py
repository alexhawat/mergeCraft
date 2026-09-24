"""A selected sticky is always updated — a blank body must not create a duplicate.

``persist_finding_ledger_to_progress_comment`` guarded its update branch on a
non-empty existing body, so a sticky the selector returned with a blank body
fell through to ``create_issue_comment``. The guard is latent while selection
requires a marker or heading, but it becomes live the moment selection pins a
comment by id or author. The fix removes the guard; it does not widen selection
to blank bodies (a blank comment is not a sticky).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.findings import ledger
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import finding_fingerprint

if TYPE_CHECKING:
    from pathlib import Path

_PR_NUMBER = 7
_BLANK_STICKY_ID = 55


class _FakeScm:
    def __init__(self) -> None:
        self.comments: dict[int, dict[str, Any]] = {}
        self.creates = 0
        self.updates = 0
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


def _seed_record(ctx: ToolContext) -> str:
    fingerprint = finding_fingerprint(path="src/app.py", body="Missing timeout.")
    ledger.ensure_finding_ledger(ctx.tool_state).record(
        fingerprint,
        "open",
        source="inline",
        round_index=1,
    )
    return fingerprint


@pytest.mark.asyncio
async def test_blank_body_selected_sticky_is_updated_not_duplicated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scm = _FakeScm()
    scm.comments[_BLANK_STICKY_ID] = {
        "id": _BLANK_STICKY_ID,
        "body": "",
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    ctx = _ctx(tmp_path, scm)
    fingerprint = _seed_record(ctx)

    async def _select_blank(
        scm_arg: Any,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        known_comment_id: int | None = None,
    ) -> dict[str, Any]:
        return {"id": _BLANK_STICKY_ID, "body": "", "user": {"type": "Bot"}}

    monkeypatch.setattr(ledger, "fetch_sticky_progress_comment", _select_blank)

    await ledger.persist_finding_ledger_to_progress_comment(ctx)

    assert scm.updates == 1, "a selected sticky must be updated in place"
    assert scm.creates == 0, "a blank selected sticky must not produce a second comment"
    assert fingerprint in scm.comments[_BLANK_STICKY_ID]["body"]


def test_a_blank_comment_is_not_selected_as_the_sticky() -> None:
    """Selection must not be widened to blank bodies to make the guard unnecessary."""
    comments: list[dict[str, Any]] = [{"id": 1, "body": ""}, {"id": 2, "body": "   "}]
    assert all(not str(row["body"]).strip() for row in comments), (
        "the fixture must be blank, else the absence assertion is vacuous"
    )
    assert ledger.sticky_progress_comment(comments) is None
    assert ledger.sticky_progress_comment_body(comments) == ""
