"""The first publisher-login lookup must not stall the MCP server's loop (#1568).

``expected_publisher_logins`` is synchronous: on first use per run it hands the
lookup coroutine to a worker thread and then blocks on the future's
``.result()``. Called from a coroutine on the MCP server's event loop, that
blocks the loop's own thread for the two REST round trips, so every other
in-flight MCP request waits.

Async callers await ``resolve_publisher_logins(ctx)`` instead; the synchronous
accessors stay for genuinely synchronous callers.

Each case runs a 10 ms heartbeat task on the same loop and a fake SCM whose login
lookup takes 300 ms. The loop must keep ticking while the lookup is pending: a
blocked loop records zero ticks for the lookup.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from mergecraft.findings import ledger_io
from mergecraft.mcp.checkout import checkout_pr_tool, list_mergecraft_reviews
from mergecraft.mcp.comment import report_progress_tool
from mergecraft.mcp.review_threads import resolve_fixed_finding_threads
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review.authorship import expected_publisher_logins
from mergecraft.types import INCREMENTAL_REVIEW_MODE
from tests.mcp.test_checkout import _ctx_for, _pr_repo_with_two_commits, _StubGitHub
from tests.support.tool_context import make_tool_context

_LOOKUP_S = 0.3
_HEARTBEAT_S = 0.01
_MIN_TICKS = 5
_LOGIN = "mergecraft-bot"
_MERGECRAFT_BODY = "### Review\n\n---\n*via mergecraft*"
_STICKY_ID = 55
_STICKY_BODY = "## mergeCraft progress\n\nRound one.\n\n---\n*via mergecraft*"
_DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1,2 +1,3 @@\n"
    " keep\n"
    "-old\n"
    "+new\n"
    "+added\n"
)


class _Heartbeat:
    """Increment a counter every 10 ms on the running loop."""

    def __init__(self) -> None:
        self.ticks = 0
        self._task: asyncio.Task[None] | None = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(_HEARTBEAT_S)
            self.ticks += 1

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


class _SlowLoginScm:
    """SCM double whose ``GET /user`` login lookup awaits 300 ms of wall clock.

    Records the heartbeat count observed across the lookup, so a blocked loop
    (zero ticks) is distinguishable from a loop that kept running.
    """

    def __init__(self, heartbeat: _Heartbeat, *, login: str = _LOGIN) -> None:
        self.heartbeat = heartbeat
        self.login = login
        self.lookup_ticks: int | None = None
        self.login_lookups = 0

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.rstrip("/").endswith("/user"):
            self.login_lookups += 1
            before = self.heartbeat.ticks
            await asyncio.sleep(_LOOKUP_S)
            self.lookup_ticks = self.heartbeat.ticks - before
            return {"login": self.login}
        return {}

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return [_mergecraft_review()]

    async def graphql(self, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
        return {}

    async def aclose(self) -> None:
        return None


def _mergecraft_review(*, login: str = _LOGIN) -> dict[str, Any]:
    return {
        "id": 1,
        "body": _MERGECRAFT_BODY,
        "state": "COMMENTED",
        "commit_id": "a" * 40,
        "submitted_at": "2026-01-01T00:00:00Z",
        "user": {"login": login, "type": "Bot"},
    }


def _tool_ctx(tmp_path: Path, scm: Any) -> Any:
    return make_tool_context(
        tmp_path,
        trust_tier="trusted",
        scm=scm,
        github_installation_token="ghs_offline_test",
    )


class _SlowLoginGitHub(_StubGitHub):
    """Checkout double: one marker-bearing review and a slow ``GET /user``."""

    def __init__(
        self, heartbeat: _Heartbeat, *, head_sha: str, reviews: list[dict[str, Any]]
    ) -> None:
        super().__init__(head_sha=head_sha, reviews=reviews)
        self.heartbeat = heartbeat
        self.lookup_ticks: int | None = None

    async def get(self, path: str, **kwargs: Any) -> Any:
        if path.rstrip("/").endswith("/user"):
            before = self.heartbeat.ticks
            await asyncio.sleep(_LOOKUP_S)
            self.lookup_ticks = self.heartbeat.ticks - before
            return {"login": _LOGIN}
        return [] if path.endswith("/files") else {}


class _SlowLoginCommentScm(_SlowLoginScm):
    """Add the issue-comment calls the sticky progress comment needs."""

    def __init__(self, heartbeat: _Heartbeat) -> None:
        super().__init__(heartbeat)
        self.updated_ids: list[int] = []
        self.creates = 0

    async def list_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        params: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        if int((params or {}).get("page", 1)) != 1:
            return []
        return [
            # A look-alike from the shared job bot: only the resolved login proves
            # which sticky is this run's.
            {
                "id": _STICKY_ID - 1,
                "body": _STICKY_BODY,
                "user": {"login": "github-actions[bot]", "type": "Bot"},
            },
            {"id": _STICKY_ID, "body": _STICKY_BODY, "user": {"login": _LOGIN, "type": "Bot"}},
        ]

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        return []

    async def update_issue_comment(
        self, owner: str, repo: str, comment_id: int, body: str
    ) -> dict[str, Any]:
        self.updated_ids.append(comment_id)
        return {"id": comment_id, "body": body}

    async def create_issue_comment(
        self, owner: str, repo: str, issue_number: int, body: str
    ) -> dict[str, Any]:
        self.creates += 1
        return {"id": 999, "body": body}


@pytest.fixture(autouse=True)
def _clean_authorship_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep every case hermetic: the authorship rule reads the process env."""
    for name in (
        "MERGECRAFT_REVIEWER_BOT_LOGIN",
        "GITHUB_APP_ID",
        "GITHUB_APP_PRIVATE_KEY",
        "INPUT_TOKEN",
        "GITHUB_TOKEN",
    ):
        monkeypatch.delenv(name, raising=False)


# --------------------------------------------------------------------------- tools on the loop


@pytest.mark.timeout(20)
async def test_list_reviews_lets_the_loop_run_during_the_login_lookup(tmp_path: Path) -> None:
    """#1568 — listing prior reviews no longer stalls every other MCP request."""
    heartbeat = _Heartbeat()
    scm = _SlowLoginScm(heartbeat)
    ctx = _tool_ctx(tmp_path, scm)
    heartbeat.start()
    try:
        started = heartbeat.ticks
        reviews = await list_mergecraft_reviews(ctx, pull_number=7)
        elapsed = heartbeat.ticks - started
    finally:
        await heartbeat.stop()

    assert [review["id"] for review in reviews] == [1]
    assert scm.lookup_ticks is not None, "the login lookup never ran"
    assert scm.lookup_ticks >= _MIN_TICKS, "the event loop was blocked during the login lookup"
    assert elapsed >= _MIN_TICKS


@pytest.mark.timeout(20)
async def test_resolve_fixed_threads_lets_the_loop_run_during_the_login_lookup(
    tmp_path: Path,
) -> None:
    """#1568 — thread retirement resolves publishers without blocking the loop."""
    heartbeat = _Heartbeat()
    # The shared Actions bot is withheld, so the publisher set stays empty and no
    # thread listing is needed; only the lookup's effect on the loop is asserted.
    scm = _SlowLoginScm(heartbeat, login="github-actions[bot]")
    ctx = _tool_ctx(tmp_path, scm)
    ctx.tool_state.selected_mode = INCREMENTAL_REVIEW_MODE
    primary = primary_repo_state(ctx.tool_state)
    diff_path = tmp_path / "incremental.diff"
    diff_path.write_text(_DIFF, encoding="utf-8")
    primary.incremental_changed_paths = ["src/app.py"]
    primary.incremental_diff_path = str(diff_path)

    heartbeat.start()
    try:
        started = heartbeat.ticks
        resolved = await resolve_fixed_finding_threads(ctx, pull_number=7, still_raised=frozenset())
        elapsed = heartbeat.ticks - started
    finally:
        await heartbeat.stop()

    assert resolved == 0
    assert scm.lookup_ticks is not None, "the login lookup never ran"
    assert scm.lookup_ticks >= _MIN_TICKS, "the event loop was blocked during the login lookup"
    assert elapsed >= _MIN_TICKS


@pytest.mark.timeout(20)
async def test_checkout_lets_the_loop_run_during_the_login_lookup(tmp_path: Path) -> None:
    """#1568 — the checkout path that reads prior reviews keeps the loop free."""
    repo, _first, head = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
    heartbeat = _Heartbeat()
    github = _SlowLoginGitHub(heartbeat, head_sha=head, reviews=[_mergecraft_review()])
    ctx = _ctx_for(repo, github, tmp_path, mode="Review", analyzers_mode="off")
    # A publication token is what makes the run resolve ``GET /user`` at all.
    ctx.github_installation_token = "ghs_offline_test"

    heartbeat.start()
    try:
        started = heartbeat.ticks
        result = await checkout_pr_tool(ctx).execute({"pull_number": 1})
        elapsed = heartbeat.ticks - started
    finally:
        await heartbeat.stop()

    assert not result.is_error, result.content
    assert github.lookup_ticks is not None, "the login lookup never ran"
    assert github.lookup_ticks >= _MIN_TICKS, "the event loop was blocked during the login lookup"
    assert elapsed >= _MIN_TICKS


@pytest.mark.timeout(20)
@pytest.mark.parametrize("ledger_loaded", [False, True], ids=["hydrates-ledger", "ledger-loaded"])
async def test_report_progress_lets_the_loop_run_during_the_login_lookup(
    tmp_path: Path, ledger_loaded: bool
) -> None:
    """#1568 — ``report_progress`` as a run's first tool call keeps the loop free.

    With a cold ledger the hydration reaches the lookup first; with a loaded one
    the tool's own sticky lookup does.
    """
    heartbeat = _Heartbeat()
    scm = _SlowLoginCommentScm(heartbeat)
    ctx = _tool_ctx(tmp_path, scm)
    primary_repo_state(ctx.tool_state).issue_number = 7
    ctx.tool_state.finding_ledger_loaded = ledger_loaded

    heartbeat.start()
    try:
        result = await report_progress_tool(ctx).execute({"body": "Round two."})
    finally:
        await heartbeat.stop()

    assert not result.is_error, result.content
    assert scm.lookup_ticks is not None, "the login lookup never ran"
    assert scm.lookup_ticks >= _MIN_TICKS, "the event loop was blocked during the login lookup"
    assert scm.login_lookups == 1
    assert scm.updated_ids == [_STICKY_ID], "the resolved login selects this run's sticky"
    assert scm.creates == 0


@pytest.mark.timeout(20)
async def test_record_upsert_lets_the_loop_run_during_the_login_lookup(tmp_path: Path) -> None:
    """#1568 — the run-record writer resolves publishers without blocking the loop."""
    heartbeat = _Heartbeat()
    scm = _SlowLoginCommentScm(heartbeat)
    ctx = _tool_ctx(tmp_path, scm)
    primary_repo_state(ctx.tool_state).issue_number = 7

    heartbeat.start()
    try:
        await ledger_io.upsert_sticky_progress_comment(ctx, "### mergeCraft run record")
    finally:
        await heartbeat.stop()

    assert scm.lookup_ticks is not None, "the login lookup never ran"
    assert scm.lookup_ticks >= _MIN_TICKS, "the event loop was blocked during the login lookup"
    assert scm.updated_ids == [_STICKY_ID]
    assert scm.creates == 0


# --------------------------------------------------------------------------- guards


@pytest.mark.timeout(20)
async def test_sticky_scope_ends_with_its_block(tmp_path: Path) -> None:
    """Guard: a failing lookup must not leave later code inside the run's scope."""
    ctx = _tool_ctx(tmp_path, _SlowLoginCommentScm(_Heartbeat()))
    ctx.publisher_logins = frozenset({_LOGIN})
    comments = await ctx.scm.list_issue_comments("acme", "demo", 7)

    scoped: list[Any] = []

    async def _fail_inside_the_scope() -> None:
        async with ledger_io.run_sticky_scope(ctx):
            scoped.append(ledger_io.sticky_progress_comment(comments))
            raise RuntimeError("listing failed")

    with pytest.raises(RuntimeError, match="listing failed"):
        await _fail_inside_the_scope()

    unscoped = ledger_io.sticky_progress_comment(comments)
    assert [comment["id"] for comment in scoped] == [_STICKY_ID]
    assert unscoped is not None
    assert unscoped["id"] == _STICKY_ID - 1, "outside the scope the legacy rule applies again"


@pytest.mark.timeout(20)
async def test_logins_are_looked_up_once_per_run(tmp_path: Path) -> None:
    """Guard: the resolved set is cached on the context for the rest of the run."""
    heartbeat = _Heartbeat()
    scm = _SlowLoginScm(heartbeat)
    ctx = _tool_ctx(tmp_path, scm)

    first = await list_mergecraft_reviews(ctx, pull_number=7)
    second = await list_mergecraft_reviews(ctx, pull_number=7)

    assert [review["id"] for review in first] == [1]
    assert [review["id"] for review in second] == [1]
    assert scm.login_lookups == 1


def test_sync_caller_without_a_loop_still_resolves(tmp_path: Path) -> None:
    """Guard: the synchronous accessor keeps its contract for sync callers."""
    heartbeat = _Heartbeat()
    scm = _SlowLoginScm(heartbeat)
    ctx = _tool_ctx(tmp_path, scm)

    assert expected_publisher_logins(ctx) == frozenset({_LOGIN})
    assert scm.login_lookups == 1
