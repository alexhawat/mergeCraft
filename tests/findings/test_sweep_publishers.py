"""The carry-over sweep resolves its expected-publisher set and refuses to guess.

``plan_carryover`` runs after merge with no run context, so it derives the publisher
identity the way the read-side ledger does: the configured reviewer App login
(``MERGECRAFT_REVIEWER_BOT_LOGIN`` / repo config), then the app slug of the
``mergecraft-approval`` check on the head. The shared Actions login is never one, and
a sweep with no publisher identity files nothing and says why.
"""

from __future__ import annotations

from typing import Any

import pytest
from loguru import logger

from mergecraft.findings.sweep import plan_carryover
from mergecraft.scm.types import ListedItems
from tests.findings.test_sweep import FakeGitHub, _graphql_thread


class ChecksGitHub(FakeGitHub):
    """``FakeGitHub`` that also answers the approval-check lookup."""

    def __init__(self, *, app_slug: str | None, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._app_slug = app_slug

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"head": {"sha": "abc123"}}

    async def list_check_runs_for_ref(
        self, owner: str, repo: str, ref: str, **kwargs: Any
    ) -> ListedItems:
        runs: list[dict[str, Any]] = []
        if self._app_slug is not None:
            runs.append({"name": "mergecraft-approval", "app": {"slug": self._app_slug}})
        return ListedItems(items=runs, incomplete=False)


@pytest.fixture(autouse=True)
def _no_ambient_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MERGECRAFT_REVIEWER_BOT_LOGIN", raising=False)
    monkeypatch.setattr(
        "mergecraft.findings.ledger._publisher_login_from_repo_config", lambda: "", raising=True
    )


async def test_a_sweep_with_no_publisher_identity_files_nothing_and_says_why() -> None:
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        plan = await plan_carryover(FakeGitHub(), "o", "r", 7)  # type: ignore[arg-type]
    finally:
        logger.remove(sink_id)

    assert plan.to_file == []
    assert any("publisher" in line.lower() for line in captured), captured


async def test_the_configured_reviewer_app_is_the_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "mergecraft[bot]")

    plan = await plan_carryover(FakeGitHub(), "o", "r", 7)  # type: ignore[arg-type]

    assert len(plan.to_file) == 1


async def test_a_thread_by_a_different_app_is_not_swept(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "some-other-app[bot]")

    plan = await plan_carryover(FakeGitHub(), "o", "r", 7)  # type: ignore[arg-type]

    assert plan.to_file == []


async def test_the_approval_check_app_slug_names_the_publisher() -> None:
    github = ChecksGitHub(app_slug="mergecraft", threads=[_graphql_thread()])

    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert len(plan.to_file) == 1


async def test_the_shared_actions_login_is_never_a_publisher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MERGECRAFT_REVIEWER_BOT_LOGIN", "github-actions[bot]")
    thread = _graphql_thread()
    thread["comments"]["nodes"][0]["author"] = {"login": "github-actions[bot]"}

    plan = await plan_carryover(FakeGitHub(threads=[thread]), "o", "r", 7)  # type: ignore[arg-type]

    assert plan.to_file == []


async def test_an_explicit_publisher_set_overrides_derivation() -> None:
    plan = await plan_carryover(
        FakeGitHub(),  # type: ignore[arg-type]
        "o",
        "r",
        7,
        publishers=frozenset({"mergecraft[bot]"}),
    )

    assert len(plan.to_file) == 1
