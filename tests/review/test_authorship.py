"""P-17 / P12 — mergeCraft authorship is marker *and* expected publisher (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

Locked contract **TB-D7**. A review body that carries ``*via mergecraft*`` (or a
``mergecraft-finding:v1:`` marker) proves nothing on its own: anyone who can
leave a PR review can paste it. mergeCraft authorship is the marker **and** an
author login in the run's expected-publisher set:

* the configured reviewer App's bot login (``<app-slug>[bot]``);
* ``github-actions[bot]`` only when job-token publication is enabled;
* a PAT's login (``GET /user``) only when the run publishes with a PAT.

A lookup failure drops that login from the set; it never widens the match.

RED markers were reconciled after TB3 landed; every case here is a real pass.
"""

from __future__ import annotations

from typing import Any

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

    def __init__(self, *, app_response: Any = None, fail: bool = False) -> None:
        self._app_response = app_response
        self._fail = fail
        self.get_calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, path: str, **kwargs: Any) -> Any:
        self.get_calls.append((path, kwargs))
        if self._fail:
            msg = "app lookup unavailable"
            raise RuntimeError(msg)
        if path.rstrip("/").endswith("/app"):
            return self._app_response
        return None

    async def aclose(self) -> None:
        return None


def _ctx(scm: _StubScm) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=".")
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        scm=scm,  # type: ignore[arg-type]
        tool_state=state,
    )


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
