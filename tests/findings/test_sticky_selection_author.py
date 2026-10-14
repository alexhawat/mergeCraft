"""Sticky progress-comment selection trusts a publisher identity, never "any bot".

Plan 38 shipped an interim rule: a sticky was any comment whose author's
``user.type`` was ``"Bot"``. That rule is forgeable — any same-repo collaborator
with workflow permissions can post a marker-bearing comment as
``github-actions[bot]`` from a ``pull_request`` workflow, and its ledger markers
(including ``withdrawn``) would then steer the run.

Selection resolves in this order (and only this order):

1. **The run-bound progress-comment id** from the trusted workflow run's own
   evidence artefact, when one is available (see ``mcp/checkout.py``). That
   comment's author must still be a Bot and its marker must still be present.
2. **The expected-publisher set** — ``is_mergecraft_authored(comment,
   publishers=expected_publisher_logins(ctx))``. This works when the run
   publishes as an App or a PAT.
3. **Neither** (a job-token-only run with no readable artefact): select
   **nothing**; the writer creates a new progress comment and logs one warning
   naming why. A Bot-only match is *never* accepted. The cost is one comment per
   run and no cross-run ledger, but only when both identities are unavailable.

The reader functions tested here take a ``ToolContext`` because the publisher
set is resolved from the run's credentials (``review/authorship.py``), never
from a PR-forgeable env value alone.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
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
_APP_BOT_COMMENT_ID = 88
_FOREIGN_BOT_COMMENT_ID = 89
_JOB_BOT_COMMENT_ID = 90
_HEADING = "## mergeCraft progress"
_APP_SLUG = "mergecraft"
_APP_BOT_LOGIN = f"{_APP_SLUG}[bot]"
_FOREIGN_BOT_LOGIN = "other-app[bot]"
_JOB_BOT_LOGIN = "github-actions[bot]"


@contextmanager
def _capture_warnings() -> Iterator[list[str]]:
    """Attach a loguru sink at WARNING and detach it on exit."""
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        yield captured
    finally:
        loguru_logger.remove(sink_id)


def _ledger_body(*, round_index: int = 1, withdrawn: bool = False) -> str:
    fingerprint = finding_fingerprint(path="src/app.py", body="Missing timeout.")
    book = ledger.FindingLedger()
    book.record(fingerprint, "open", source="inline", round_index=round_index)
    if withdrawn:
        book.record(
            finding_fingerprint(path="src/app.py", body="A forged withdrawal."),
            "withdrawn",
            source="verifier-drop",
            round_index=round_index,
        )
    return f"{_HEADING}\n\nRound one.\n\n{book.render_ledger_block()}\n"


def _comment(
    *,
    comment_id: int,
    login: str,
    user_type: str = "Bot",
    body: str | None = None,
) -> dict[str, Any]:
    return {
        "id": comment_id,
        "body": body if body is not None else _ledger_body(),
        "user": {"login": login, "type": user_type},
    }


def _human_comment(
    *, comment_id: int = _HUMAN_COMMENT_ID, body: str | None = None
) -> dict[str, Any]:
    return _comment(comment_id=comment_id, login="some-human", user_type="User", body=body)


def _app_bot_comment(
    *, comment_id: int = _APP_BOT_COMMENT_ID, body: str | None = None
) -> dict[str, Any]:
    return _comment(comment_id=comment_id, login=_APP_BOT_LOGIN, body=body)


def _foreign_bot_comment(
    *, comment_id: int = _FOREIGN_BOT_COMMENT_ID, body: str | None = None
) -> dict[str, Any]:
    return _comment(comment_id=comment_id, login=_FOREIGN_BOT_LOGIN, body=body)


def _job_bot_comment(
    *, comment_id: int = _JOB_BOT_COMMENT_ID, body: str | None = None
) -> dict[str, Any]:
    return _comment(comment_id=comment_id, login=_JOB_BOT_LOGIN, body=body)


class _FakeScm:
    """Minimal SCM stub: comments plus the ``/app`` / ``/user`` authorship lookups."""

    def __init__(
        self,
        comments: list[dict[str, Any]],
        *,
        app_response: Any = None,
        user_response: Any = None,
    ) -> None:
        self.comments = {int(row["id"]): dict(row) for row in comments}
        self._app_response = app_response
        self._user_response = user_response
        self.creates = 0
        self.updates = 0
        self.updated_ids: list[int] = []
        self._next_id = 100

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.rstrip("/").endswith("/app"):
            return self._app_response
        if path.rstrip("/").endswith("/user"):
            return self._user_response
        return None

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
            "user": {"login": _JOB_BOT_LOGIN, "type": "Bot"},
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


def _clear_publisher_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Drop every ambient publisher identity so the run resolves from the stub only."""
    for name in (
        "MERGECRAFT_REVIEWER_BOT_LOGIN",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "INPUT_TOKEN",
        "GITHUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


def _ctx(
    tmp_path: Path,
    scm: _FakeScm,
    *,
    token: str = "",
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.pr_number = _PR_NUMBER
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=_PR_NUMBER, is_pr=True),
        ),
        scm=scm,
        github_installation_token=token,
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


def _app_publisher_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ToolContext:
    """A run publishing as an App: ``GET /app`` answers with the App slug."""
    _clear_publisher_env(monkeypatch)
    scm = _FakeScm([], app_response={"slug": _APP_SLUG})
    return _ctx(tmp_path, scm)


def _job_token_ctx(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, comments: list[dict[str, Any]]
) -> ToolContext:
    """A job-token-only run: no App, no PAT — the expected-publisher set is empty."""
    _clear_publisher_env(monkeypatch)
    scm = _FakeScm(comments)
    return _ctx(tmp_path, scm, token="job-token")


def _select(
    ctx: ToolContext,
    comments: list[dict[str, Any]],
    *,
    run_bound_comment_id: int | None = None,
) -> dict[str, Any] | None:
    return ledger.select_sticky_progress_comment(
        ctx, comments, run_bound_comment_id=run_bound_comment_id
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


# ── step 3: a Bot-only match is never the sticky ─────────────────────────────


def test_a_human_comment_with_a_ledger_marker_is_not_selected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    human = _human_comment()
    assert ledger.LEDGER_MARKER_V2_PREFIX in str(human["body"]), (
        "the fixture must carry a marker, else the absence assertion is vacuous"
    )
    ctx = _job_token_ctx(tmp_path, monkeypatch, [human])

    assert _select(ctx, [human]) is None


def test_a_github_actions_bot_comment_with_ledger_markers_is_not_selected_on_a_job_token_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The shared job bot is forgeable, so its markers — including ``withdrawn`` —
    must never win selection. The writer creates a fresh comment instead."""
    forged = _job_bot_comment(body=_ledger_body(withdrawn=True))
    assert ledger.LEDGER_MARKER_V2_PREFIX in str(forged["body"])
    assert "withdrawn" in str(forged["body"]), (
        "the fixture must carry a withdrawn record, else the assertion is weaker than the risk"
    )
    ctx = _job_token_ctx(tmp_path, monkeypatch, [forged])

    assert _select(ctx, [forged]) is None


@pytest.mark.asyncio
async def test_persist_with_an_empty_publisher_set_creates_and_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No run-bound id and no publisher identity: create a new sticky and say why."""
    forged = _job_bot_comment(body=_ledger_body(withdrawn=True))
    ctx = _job_token_ctx(tmp_path, monkeypatch, [forged])
    fingerprint = _seed_record(ctx)
    forged_body_before = str(forged["body"])

    with _capture_warnings() as warnings:
        await ledger.persist_finding_ledger_to_progress_comment(ctx)

    scm = ctx.scm
    assert isinstance(scm, _FakeScm)
    assert scm.updates == 0, "the forgeable job-bot comment must not be written to"
    assert scm.creates == 1, "the ledger must land in a new comment"
    assert scm.comments[_JOB_BOT_COMMENT_ID]["body"] == forged_body_before
    created = scm.comments[max(scm.comments)]
    assert fingerprint in str(created["body"])
    assert any("publisher" in message.lower() for message in warnings), (
        f"one warning must name why no identity resolved; got {warnings!r}"
    )


# ── step 2: the expected publisher set ───────────────────────────────────────


def test_an_app_publisher_selects_its_own_bot_and_not_a_foreign_app(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = _foreign_bot_comment()
    mine = _app_bot_comment()
    ctx = _app_publisher_ctx(tmp_path, monkeypatch)

    selected = _select(ctx, [foreign, mine])

    assert selected is not None
    assert selected["id"] == _APP_BOT_COMMENT_ID


def test_an_app_publisher_does_not_select_a_foreign_app_on_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    foreign = _foreign_bot_comment()
    ctx = _app_publisher_ctx(tmp_path, monkeypatch)

    assert _select(ctx, [foreign]) is None


def test_ledger_marker_preference_holds_among_marked_publisher_comments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A heading-only publisher comment does not beat a publisher comment carrying markers."""
    heading_only = _app_bot_comment(
        comment_id=91,
        body=f"{_HEADING}\n\nOlder prose without markers.",
    )
    marked = _app_bot_comment()
    ctx = _app_publisher_ctx(tmp_path, monkeypatch)

    selected = _select(ctx, [heading_only, marked])

    assert selected is not None
    assert selected["id"] == _APP_BOT_COMMENT_ID


# ── step 1: the run-bound id wins ────────────────────────────────────────────


def test_the_run_bound_comment_id_wins_when_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The trusted run's own artefact names the sticky; it outranks the publisher scan."""
    other = _app_bot_comment(comment_id=92)
    bound = _app_bot_comment(comment_id=93)
    ctx = _app_publisher_ctx(tmp_path, monkeypatch)

    selected = _select(ctx, [other, bound], run_bound_comment_id=93)

    assert selected is not None
    assert selected["id"] == 93


def test_the_run_bound_comment_id_must_still_name_a_bot_and_carry_a_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A forged or stale id is not trusted: the author must be a Bot and the marker present."""
    human = _human_comment(comment_id=94)
    bare_bot = _job_bot_comment(comment_id=95, body=f"{_HEADING}\n\nNo markers here.\n")
    ctx = _job_token_ctx(tmp_path, monkeypatch, [human, bare_bot])

    assert _select(ctx, [human], run_bound_comment_id=94) is None
    assert _select(ctx, [bare_bot], run_bound_comment_id=95) is None


def test_the_run_bound_comment_id_alone_selects_on_a_job_token_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """HS8 exists for the job-token-only run: the trusted run's own artefact names a
    comment the publisher set can never prove (it was posted as the shared job bot).
    Step 1 selects it by id, so the checkpoint survives even when step 2 cannot."""
    bound = _job_bot_comment(comment_id=96)
    ctx = _job_token_ctx(tmp_path, monkeypatch, [bound])

    selected = _select(ctx, [bound], run_bound_comment_id=96)

    assert selected is not None
    assert selected["id"] == 96


# ── hydrate / upsert keep ignoring a human marker ────────────────────────────


@pytest.mark.asyncio
async def test_hydrate_ignores_a_human_ledger_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    human = _human_comment()
    ctx = _job_token_ctx(tmp_path, monkeypatch, [human])
    scm = ctx.scm
    assert isinstance(scm, _FakeScm)
    assert ledger.LEDGER_MARKER_V2_PREFIX in str(scm.comments[_HUMAN_COMMENT_ID]["body"]), (
        "the fixture must carry a marker, else the absence assertion is vacuous"
    )

    loaded = await ledger.hydrate_finding_ledger_from_progress_comment(ctx)

    assert isinstance(loaded, ledger.FindingLedger), "hydrate must return the run's ledger"
    assert loaded.records() == [], "a human comment must not seed the run's ledger"


@pytest.mark.asyncio
async def test_persist_ignores_a_human_ledger_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    human = _human_comment()
    ctx = _job_token_ctx(tmp_path, monkeypatch, [human])
    scm = ctx.scm
    assert isinstance(scm, _FakeScm)
    fingerprint = _seed_record(ctx)
    human_body_before = scm.comments[_HUMAN_COMMENT_ID]["body"]

    await ledger.persist_finding_ledger_to_progress_comment(ctx)

    assert scm.creates == 1, "the ledger must land in a new comment"
    assert scm.updates == 0, "the human's comment must not be written to"
    assert scm.comments[_HUMAN_COMMENT_ID]["body"] == human_body_before
    created = scm.comments[max(scm.comments)]
    assert fingerprint in created["body"]


@pytest.mark.asyncio
async def test_upsert_ignores_a_human_ledger_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    human = _human_comment()
    ctx = _job_token_ctx(tmp_path, monkeypatch, [human])
    scm = ctx.scm
    assert isinstance(scm, _FakeScm)
    human_body_before = scm.comments[_HUMAN_COMMENT_ID]["body"]

    await ledger.upsert_sticky_progress_comment(
        ctx,
        f"{ledger.DETERMINISTIC_RECORD_MARKER}\n### mergeCraft run record\n",
    )

    assert scm.creates == 1, "the record must land in a new comment"
    assert scm.updates == 0, "the human's comment must not be written to"
    assert scm.comments[_HUMAN_COMMENT_ID]["body"] == human_body_before
    created = scm.comments[max(scm.comments)]
    assert ledger.DETERMINISTIC_RECORD_MARKER in str(created["body"])
