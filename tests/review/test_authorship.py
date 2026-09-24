"""P-17 / P12 — mergeCraft authorship is marker *and* expected publisher (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

Locked contract **TB-D7**. A review body that carries ``*via mergecraft*`` (or a
``mergecraft-finding:v1:`` marker) proves nothing on its own: anyone who can
leave a PR review can paste it. mergeCraft authorship is the marker **and** an
author login in the run's expected-publisher set:

* the configured reviewer App's bot login (``<app-slug>[bot]``);
* a PAT's login (``GET /user``) only when the run publishes with a PAT.

The shared Actions job bot (``github-actions[bot]``) is **never** accepted: any
same-repo collaborator with workflow permissions can post a marker-bearing
review as that login, so a forged ``commit_id`` could become the checkpoint and
the next incremental review would diff *from* it. A run whose only candidate is
the shared bot therefore publishes no attributable identity at all — the set is
empty (fail-closed) and the withholding is warned once, naming the identity and
the App/PAT remedy.

A lookup failure drops that login from the set; it never widens the match.

RED markers were reconciled after TB3 landed; every case here is a real pass.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state

_MERGECRAFT_BODY = "### Review\n\n---\n*via mergecraft*"
_MARKER = frozenset({"mergecraft[bot]"})


def _is_authored(item: dict[str, Any], publishers: frozenset[str]) -> bool:
    from mergecraft.review.authorship import is_mergecraft_authored

    return is_mergecraft_authored(item, publishers=publishers)


def _expected_publishers(ctx: ToolContext) -> frozenset[str]:
    from mergecraft.review.authorship import expected_publisher_logins

    return expected_publisher_logins(ctx)


class _StubScm:
    """Records ``get`` calls and answers (or raises) on demand."""

    def __init__(
        self,
        *,
        app_response: Any = None,
        user_response: Any = None,
        fail: bool = False,
    ) -> None:
        self._app_response = app_response
        self._user_response = user_response
        self._fail = fail
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.get_calls.append((path, kwargs))
        if self._fail:
            msg = "app lookup unavailable"
            raise RuntimeError(msg)
        if path.rstrip("/").endswith("/app"):
            return self._app_response
        if path.rstrip("/").endswith("/user"):
            return self._user_response
        return None

    async def aclose(self) -> None:
        return None


def _ctx(scm: _StubScm, *, token: str = "") -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        scm=scm,  # type: ignore[arg-type]
        tool_state=state,
        github_installation_token=token,
    )


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


def _capture_loguru_warnings() -> tuple[list[str], int]:
    from loguru import logger as loguru_logger

    captured: list[str] = []
    sink_id = loguru_logger.add(lambda msg: captured.append(str(msg)), level="WARNING")
    return captured, sink_id


# ── is_mergecraft_authored: marker AND publisher ─────────────────────────────


def test_marker_from_an_expected_publisher_is_authored() -> None:
    """TB-D7 — marker plus an expected-publisher login counts."""
    item = {"body": _MERGECRAFT_BODY, "user": {"login": "mergecraft[bot]", "type": "Bot"}}
    assert _is_authored(item, _MARKER) is True


def test_marker_from_a_foreign_app_bot_is_not_authored() -> None:
    """TB-D7 — another App's bot is not the publisher, however bot-shaped."""
    item = {"body": _MERGECRAFT_BODY, "user": {"login": "other-app[bot]", "type": "Bot"}}
    assert _is_authored(item, _MARKER) is False


def test_marker_from_a_human_is_not_authored() -> None:
    """TB-D7 — a human who pastes the marker is not mergeCraft."""
    item = {"body": _MERGECRAFT_BODY, "user": {"login": "random-user", "type": "User"}}
    assert _is_authored(item, _MARKER) is False


def test_no_marker_is_not_authored() -> None:
    """TB-D7 — the marker half is still required."""
    item = {"body": "LGTM, nice work", "user": {"login": "mergecraft[bot]", "type": "Bot"}}
    assert _is_authored(item, _MARKER) is False


def test_empty_publisher_set_authorizes_nothing() -> None:
    """TB-D7 — an unresolved set never widens the match."""
    item = {"body": _MERGECRAFT_BODY, "user": {"login": "mergecraft[bot]", "type": "Bot"}}
    assert _is_authored(item, frozenset()) is False


def test_missing_user_is_not_authored() -> None:
    """TB-D7 — a marker review with no author is not attributable."""
    assert _is_authored({"body": _MERGECRAFT_BODY}, _MARKER) is False


# ── expected_publisher_logins ────────────────────────────────────────────────


def test_expected_publishers_includes_the_app_bot_login() -> None:
    """TB-D7 — the configured reviewer App's bot login is ``<slug>[bot]``."""
    ctx = _ctx(_StubScm(app_response={"slug": "mergecraft"}))
    publishers = _expected_publishers(ctx)
    assert isinstance(publishers, frozenset)
    assert "mergecraft[bot]" in publishers


def test_failed_lookup_drops_the_login_and_never_widens() -> None:
    """TB-D7 — a lookup failure removes the login; it cannot add one."""
    ctx = _ctx(_StubScm(fail=True))
    publishers = _expected_publishers(ctx)

    assert isinstance(publishers, frozenset)
    marker = {"body": _MERGECRAFT_BODY, "user": {"login": "mergecraft[bot]", "type": "Bot"}}
    assert _is_authored(marker, publishers) is False


def test_expected_publishers_is_built_once_per_run() -> None:
    """TB-D7 — the set is built once and cached on the context."""
    scm = _StubScm(app_response={"slug": "mergecraft"})
    ctx = _ctx(scm)

    first = _expected_publishers(ctx)
    calls_after_first = len(scm.get_calls)
    second = _expected_publishers(ctx)

    assert second == first
    assert len(scm.get_calls) == calls_after_first


def test_expected_publishers_returns_a_frozenset_without_an_app() -> None:
    """Guard — the helper is total even with no App configured."""
    ctx = _ctx(_StubScm(app_response=None))
    publishers = _expected_publishers(ctx)
    assert isinstance(publishers, frozenset)


# ── TB6 — the running-loop branch production actually uses ───────────────────
#
# ``expected_publisher_logins`` is synchronous by contract, but the production
# caller (``list_mergecraft_reviews``) is async, so ``_await_sync`` takes its
# ``asyncio.get_running_loop()`` branch and drives the single ``ctx.scm.get`` in
# a worker thread. The sync tests above exercise the other branch; these call
# the helper from inside a running loop so the production branch is the one
# under test.


@pytest.mark.asyncio
async def test_expected_publishers_resolves_from_a_running_loop() -> None:
    """TB6 — the App lookup is driven to completion from inside a running loop."""
    ctx = _ctx(_StubScm(app_response={"slug": "mergecraft"}))

    publishers = _expected_publishers(ctx)

    assert isinstance(publishers, frozenset)
    assert "mergecraft[bot]" in publishers


@pytest.mark.asyncio
async def test_failed_lookup_from_a_running_loop_never_widens() -> None:
    """TB6 — a lookup failure on the running-loop branch drops the login."""
    ctx = _ctx(_StubScm(fail=True))

    publishers = _expected_publishers(ctx)

    assert isinstance(publishers, frozenset)
    marker = {"body": _MERGECRAFT_BODY, "user": {"login": "mergecraft[bot]", "type": "Bot"}}
    assert _is_authored(marker, publishers) is False


# ── The shared Actions job bot is never accepted (fail-closed, P-6/P-8) ──────
#
# ``github-actions[bot]`` is a shared identity, not an App identity: any
# same-repo collaborator with workflow permissions can add a ``pull_request``
# workflow on their branch that posts a marker-bearing review as that login,
# moving the checkpoint to a commit of their choosing. The declared login and
# the publication token are therefore *withheld*, and a run with no App and no
# PAT resolves to the empty set and says so once at ``warning`` — never a silent
# empty set, never a trusted job bot.

_APP_BOT_BODY = "### Review\n\n---\n*via mergecraft*"


def test_declared_github_actions_bot_login_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-App workflow's declared shared login is withdrawn, not added."""
    from mergecraft.review.authorship import GITHUB_ACTIONS_BOT_LOGIN

    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", GITHUB_ACTIONS_BOT_LOGIN)
    publishers = _expected_publishers(_ctx(_StubScm(app_response=None)))

    assert publishers == frozenset()
    assert GITHUB_ACTIONS_BOT_LOGIN not in publishers


@pytest.mark.parametrize("declared", ["github-actions[bot]", "GitHub-Actions[Bot]"])
def test_withheld_shared_bot_login_is_matched_case_insensitively(
    declared: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The withholding cannot be bypassed by a case variant of the login."""
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", declared)
    publishers = _expected_publishers(_ctx(_StubScm(app_response=None)))

    assert publishers == frozenset()


def test_declared_app_bot_login_is_still_added(monkeypatch: pytest.MonkeyPatch) -> None:
    """A real App bot login declared by the review step remains a publisher."""
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "myapp[bot]")
    publishers = _expected_publishers(_ctx(_StubScm(app_response=None)))

    assert publishers == frozenset({"myapp[bot]"})


def test_declared_shared_bot_does_not_suppress_a_real_app_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard — with an App present the withheld login must not empty the set."""
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "github-actions[bot]")
    publishers = _expected_publishers(_ctx(_StubScm(app_response={"slug": "mergecraft"})))

    assert "mergecraft[bot]" in publishers


def test_job_token_publication_adds_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Actions job token is indistinguishable from another workflow's."""
    monkeypatch.setenv("INPUT_TOKEN", "job-token")
    monkeypatch.setenv("GITHUB_TOKEN", "job-token")
    publishers = _expected_publishers(_ctx(_StubScm(app_response=None), token="job-token"))

    assert publishers == frozenset()


def test_pat_publication_adds_the_viewer_login(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caller PAT answers ``GET /user``, so its login is a publisher."""
    monkeypatch.delenv("INPUT_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    publishers = _expected_publishers(
        _ctx(
            _StubScm(app_response=None, user_response={"login": "mergecraft-ci"}),
            token="pat-token",
        )
    )

    assert publishers == frozenset({"mergecraft-ci"})


def test_withheld_shared_bot_warns_once_naming_the_identity_and_remedy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P-8 — an empty set is stated once, naming the identity and the remedy."""
    from loguru import logger as loguru_logger

    from mergecraft.review.authorship import GITHUB_ACTIONS_BOT_LOGIN

    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", GITHUB_ACTIONS_BOT_LOGIN)
    captured, sink_id = _capture_loguru_warnings()
    try:
        publishers = _expected_publishers(_ctx(_StubScm(app_response=None)))
    finally:
        loguru_logger.remove(sink_id)

    assert publishers == frozenset()
    assert len(captured) == 1
    message = captured[0]
    assert GITHUB_ACTIONS_BOT_LOGIN in message
    assert "Incremental checkpoints" in message
    assert "reviewer App" in message or "PAT" in message


def test_job_token_withholding_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """P-8 — the withheld job-token provenance is also announced, once."""
    from loguru import logger as loguru_logger

    monkeypatch.setenv("INPUT_TOKEN", "job-token")
    captured, sink_id = _capture_loguru_warnings()
    try:
        publishers = _expected_publishers(_ctx(_StubScm(app_response=None), token="job-token"))
    finally:
        loguru_logger.remove(sink_id)

    assert publishers == frozenset()
    assert len(captured) == 1
    assert "github-actions[bot]" in captured[0]


def test_job_token_viewer_answering_with_the_shared_bot_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MC-e4a36e — ``GET /user`` answers ``github-actions[bot]`` for the job token.

    A truthy viewer must not be added before the withholding: that ordering
    would put the shared bot back in the set and let a same-repo PR forge a
    marker-bearing review to move the incremental checkpoint.
    """
    from loguru import logger as loguru_logger

    monkeypatch.setenv("INPUT_TOKEN", "job-token")
    monkeypatch.setenv("GITHUB_TOKEN", "job-token")
    scm = _StubScm(app_response=None, user_response={"login": "github-actions[bot]"})
    captured, sink_id = _capture_loguru_warnings()
    try:
        publishers = _expected_publishers(_ctx(scm, token="job-token"))
    finally:
        loguru_logger.remove(sink_id)

    assert publishers == frozenset()
    assert len(captured) == 1
    assert "github-actions[bot]" in captured[0]
    # The login is consulted (a PAT carried through INPUT_TOKEN is only
    # distinguishable by its ``/user`` answer); the shared-bot answer is what
    # must never be admitted.
    assert [path for path, _ in scm.get_calls if path.rstrip("/").endswith("/user")]


def test_pat_carried_in_the_action_token_input_is_a_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MC-e4a36e — a PAT supplied via the Action's ``token:`` input lands in INPUT_TOKEN.

    Classifying the token by provenance would call this PAT the shared job bot
    and silently drop its login; only the ``/user`` answer can decide.
    """
    monkeypatch.setenv("INPUT_TOKEN", "pat-token")
    scm = _StubScm(app_response=None, user_response={"login": "mergecraft-ci"})
    publishers = _expected_publishers(_ctx(scm, token="pat-token"))

    assert publishers == frozenset({"mergecraft-ci"})


def test_app_configured_without_a_declared_login_still_warns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P-8 — an empty set never stays silent, whichever path emptied it."""
    from loguru import logger as loguru_logger

    monkeypatch.setenv("GITHUB_APP_ID", "12345")
    monkeypatch.setenv("GITHUB_APP_PRIVATE_KEY", "-----BEGIN KEY-----")
    captured, sink_id = _capture_loguru_warnings()
    try:
        publishers = _expected_publishers(_ctx(_StubScm(app_response=None), token="job-token"))
    finally:
        loguru_logger.remove(sink_id)

    assert publishers == frozenset()
    assert len(captured) == 1
    assert "unavailable" in captured[0]


def test_viewer_answering_with_the_shared_bot_is_withheld_off_the_job_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive — a viewer that answers with the shared bot proves nothing."""
    scm = _StubScm(app_response=None, user_response={"login": "GitHub-Actions[Bot]"})
    publishers = _expected_publishers(_ctx(scm, token="some-installation-token"))

    assert publishers == frozenset()


def test_app_slug_answering_with_the_shared_bot_is_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MC-e4a36e — the invariant holds over **every** source, not just two.

    ``GET /app`` requires a JWT today, so this path is latent rather than live;
    the set-level filter is what makes it unreachable if that ever changes.
    """
    scm = _StubScm(app_response={"slug": "github-actions"}, user_response=None)
    publishers = _expected_publishers(_ctx(scm, token="job-token"))

    assert publishers == frozenset()


def test_is_mergecraft_authored_refuses_the_job_bot_on_a_job_token_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A job-token run cannot claim authorship: the marker alone proves nothing."""
    monkeypatch.setenv("INPUT_TOKEN", "job-token")
    publishers = _expected_publishers(_ctx(_StubScm(app_response=None), token="job-token"))

    forged = {
        "body": _APP_BOT_BODY,
        "user": {"login": "github-actions[bot]", "type": "Bot"},
    }
    assert publishers == frozenset()
    assert _is_authored(forged, publishers) is False
