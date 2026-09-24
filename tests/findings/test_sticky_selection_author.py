"""Only a bot-authored comment may be read as the sticky progress state.

Sticky selection trusted the body alone: any participant could post a ledger
marker (or quote the heading/footer) and win selection, after which a later
write fails for want of permission and the real ledger is never persisted.
The interim trust rule accepts a comment only when ``user.type == "Bot"``. The
ledger-marker preference stays, applied *after* the author filter.
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
_HUMAN_COMMENT_ID = 77
_BOT_COMMENT_ID = 88
_HEADING = "## mergeCraft progress"


def _ledger_body(*, round_index: int = 1) -> str:
    fingerprint = finding_fingerprint(path="src/app.py", body="Missing timeout.")
    book = ledger.FindingLedger()
    book.record(fingerprint, "open", source="inline", round_index=round_index)
    return f"{_HEADING}\n\nRound one.\n\n{book.render_ledger_block()}\n"


def _human_comment(
    *, comment_id: int = _HUMAN_COMMENT_ID, body: str | None = None
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body if body is not None else _ledger_body(),
        "user": {"login": "some-human", "type": "User"},
    }


def _bot_comment(*, comment_id: int = _BOT_COMMENT_ID, body: str | None = None) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body if body is not None else _ledger_body(),
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }


class _FakeScm:
    def __init__(self, comments: list[dict[str, Any]]) -> None:
        self.comments = {int(row["id"]): dict(row) for row in comments}
        self.creates = 0
        self.updates = 0
        self.updated_ids: list[int] = []
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


def _seed_record(ctx: ToolContext) -> str:
    fingerprint = finding_fingerprint(path="src/app.py", body="Missing timeout.")
    ledger.ensure_finding_ledger(ctx.tool_state).record(
        fingerprint,
        "open",
        source="inline",
        round_index=1,
    )
    return fingerprint


def test_a_human_comment_with_a_ledger_marker_is_not_selected() -> None:
    human = _human_comment()
    assert ledger.LEDGER_MARKER_V2_PREFIX in str(human["body"]), (
        "the fixture must carry a marker, else the absence assertion is vacuous"
    )
    comments: list[dict[str, Any]] = [human]
    assert ledger.sticky_progress_comment(comments) is None
    assert ledger.sticky_progress_comment_body(comments) == ""


def test_a_bot_sticky_is_selected() -> None:
    comments: list[dict[str, Any]] = [_bot_comment()]
    selected = ledger.sticky_progress_comment(comments)
    assert selected is not None
    assert selected["id"] == _BOT_COMMENT_ID
    assert ledger.sticky_progress_comment_body(comments) == _ledger_body()


def test_ledger_marker_preference_holds_among_bot_comments() -> None:
    """A bot heading-only comment does not beat a bot comment carrying markers."""
    heading_only = _bot_comment(
        comment_id=90,
        body=f"{_HEADING}\n\nOlder prose without markers.",
    )
    comments: list[dict[str, Any]] = [heading_only, _bot_comment()]
    selected = ledger.sticky_progress_comment(comments)
    assert selected is not None
    assert selected["id"] == _BOT_COMMENT_ID
    assert ledger.sticky_progress_comment_body(comments) == _ledger_body()


@pytest.mark.asyncio
async def test_hydrate_ignores_a_human_ledger_marker(tmp_path: Path) -> None:
    scm = _FakeScm([_human_comment()])
    ctx = _ctx(tmp_path, scm)
    assert ledger.LEDGER_MARKER_V2_PREFIX in str(scm.comments[_HUMAN_COMMENT_ID]["body"]), (
        "the fixture must carry a marker, else the absence assertion is vacuous"
    )

    loaded = await ledger.hydrate_finding_ledger_from_progress_comment(ctx)

    assert isinstance(loaded, ledger.FindingLedger), "hydrate must return the run's ledger"
    assert loaded.records() == [], "a human comment must not seed the run's ledger"


@pytest.mark.asyncio
async def test_persist_ignores_a_human_ledger_marker(tmp_path: Path) -> None:
    scm = _FakeScm([_human_comment()])
    ctx = _ctx(tmp_path, scm)
    fingerprint = _seed_record(ctx)
    human_body_before = scm.comments[_HUMAN_COMMENT_ID]["body"]

    await ledger.persist_finding_ledger_to_progress_comment(ctx)

    assert scm.creates == 1, "the ledger must land in a new bot-owned comment"
    assert scm.updates == 0, "the human's comment must not be written to"
    assert scm.comments[_HUMAN_COMMENT_ID]["body"] == human_body_before
    created = scm.comments[max(scm.comments)]
    assert fingerprint in created["body"]


@pytest.mark.asyncio
async def test_upsert_ignores_a_human_ledger_marker(tmp_path: Path) -> None:
    scm = _FakeScm([_human_comment()])
    ctx = _ctx(tmp_path, scm)
    human_body_before = scm.comments[_HUMAN_COMMENT_ID]["body"]

    await ledger.upsert_sticky_progress_comment(
        ctx,
        f"{ledger.DETERMINISTIC_RECORD_MARKER}\n### mergeCraft run record\n",
    )

    assert scm.creates == 1, "the record must land in a new bot-owned comment"
    assert scm.updates == 0, "the human's comment must not be written to"
    assert scm.comments[_HUMAN_COMMENT_ID]["body"] == human_body_before
    created = scm.comments[max(scm.comments)]
    assert ledger.DETERMINISTIC_RECORD_MARKER in str(created["body"])
