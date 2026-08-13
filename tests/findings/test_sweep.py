"""Carryover sweep: reading threads, deduping by fingerprint, filing issues."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mergecraft.findings.sweep import (
    apply_carryover,
    filed_fingerprints,
    plan_carryover,
)
from mergecraft.findings.threads import fetch_review_threads
from mergecraft.review_resolution import finding_fingerprints_in
from mergecraft.review_taxonomy import stamp_finding_fingerprint

_PATH = "src/app.py"
_BODY = stamp_finding_fingerprint(path=_PATH, body="Missing timeout on the retry loop.")
_FP = next(iter(finding_fingerprints_in(_BODY)))
_OTHER = stamp_finding_fingerprint(path=_PATH, body="Unchecked index access.")
_OTHER_FP = next(iter(finding_fingerprints_in(_OTHER)))


def _graphql_thread(
    *, node_id: str = "T1", body: str = _BODY, resolved: bool = False
) -> dict[str, Any]:
    return {
        "id": node_id,
        "isResolved": resolved,
        "isOutdated": False,
        "comments": {
            "nodes": [
                {
                    "databaseId": 1,
                    "body": body,
                    "author": {"login": "mergecraft[bot]"},
                    "path": _PATH,
                    "line": 42,
                    "originalLine": 40,
                    "url": "https://github.com/o/r/pull/7#discussion_r1",
                    "createdAt": "2026-08-13T07:13:58Z",
                }
            ]
        },
    }


class FakeGitHub:
    """Records writes and replays canned reads, in GitHubClient's shape."""

    def __init__(
        self,
        *,
        threads: list[dict[str, Any]] | None = None,
        total_count: int | None = None,
        issues: list[dict[str, Any]] | None = None,
        create_issue_error: Exception | None = None,
    ) -> None:
        self._threads = threads if threads is not None else [_graphql_thread()]
        self._total = total_count if total_count is not None else len(self._threads)
        self._issues = issues or []
        self._create_issue_error = create_issue_error
        self.created: list[dict[str, Any]] = []
        self.labels_created: list[str] = []
        self.issue_pages: list[dict[str, Any]] = []

    async def graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {"totalCount": self._total, "nodes": self._threads}
                }
            }
        }

    async def list_issues(self, owner: str, repo: str, **kwargs: Any) -> list[dict[str, Any]]:
        params = kwargs.get("params") or {}
        self.issue_pages.append(params)
        return self._issues if int(params.get("page", 1)) == 1 else []

    async def create_label(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        self.labels_created.append(str(kwargs.get("name")))
        return {"name": kwargs.get("name")}

    async def create_issue(self, owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        if self._create_issue_error is not None:
            raise self._create_issue_error
        self.created.append(kwargs)
        number = len(self.created)
        return {"number": number, "html_url": f"https://github.com/{owner}/{repo}/issues/{number}"}


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.github.com/x")
    return httpx.HTTPStatusError(
        "boom", request=request, response=httpx.Response(status, request=request)
    )


async def test_fetch_normalizes_threads_and_reports_no_truncation() -> None:
    page = await fetch_review_threads(FakeGitHub(), "o", "r", 7)  # type: ignore[arg-type]

    assert page.truncated is False
    assert page.total_count == 1
    comment = page.threads[0]["comments"][0]
    assert comment["id"] == 1
    assert comment["line"] == 42
    assert comment["url"].endswith("#discussion_r1")


async def test_fetch_falls_back_to_the_original_line_when_the_anchor_moved() -> None:
    thread = _graphql_thread()
    thread["comments"]["nodes"][0]["line"] = None

    page = await fetch_review_threads(FakeGitHub(threads=[thread]), "o", "r", 7)  # type: ignore[arg-type]

    assert page.threads[0]["comments"][0]["line"] == 40


async def test_fetch_reports_truncation_when_a_pr_exceeds_one_page() -> None:
    page = await fetch_review_threads(
        FakeGitHub(threads=[_graphql_thread()], total_count=150),  # type: ignore[arg-type]
        "o",
        "r",
        7,
    )

    assert page.truncated is True
    assert page.total_count == 150


async def test_fetch_drops_resolved_threads_by_default() -> None:
    github = FakeGitHub(threads=[_graphql_thread(resolved=True)])

    assert (await fetch_review_threads(github, "o", "r", 7)).threads == []  # type: ignore[arg-type]
    assert (await fetch_review_threads(github, "o", "r", 7, include_resolved=True)).threads  # type: ignore[arg-type]


async def test_plan_files_a_finding_that_has_no_issue_yet() -> None:
    github = FakeGitHub()

    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert [f.fingerprint for f in plan.to_file] == [_FP]
    assert plan.already_filed == []


async def test_plan_skips_a_finding_an_existing_issue_already_carries() -> None:
    github = FakeGitHub(
        issues=[{"number": 5, "body": f"old\n\n<!-- mergecraft-finding:v1:{_FP} -->"}]
    )

    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert plan.to_file == []
    assert [f.fingerprint for f in plan.already_filed] == [_FP]


async def test_a_closed_carryover_issue_still_counts_as_filed() -> None:
    """The finding was dealt with, not lost — re-filing it would be noise."""
    github = FakeGitHub(
        issues=[{"number": 5, "state": "closed", "body": f"<!-- mergecraft-finding:v1:{_FP} -->"}]
    )

    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert plan.to_file == []
    assert github.issue_pages[0]["state"] == "all"


async def test_two_threads_with_the_same_finding_produce_one_issue() -> None:
    github = FakeGitHub(threads=[_graphql_thread(node_id="T1"), _graphql_thread(node_id="T2")])

    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert len(plan.to_file) == 1
    assert len(plan.already_filed) == 1


async def test_plan_does_not_read_issues_when_nothing_survives() -> None:
    github = FakeGitHub(threads=[_graphql_thread(body="a human wrote this")])

    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert plan.to_file == []
    assert github.issue_pages == []


async def test_apply_files_one_labelled_issue_carrying_the_fingerprint() -> None:
    github = FakeGitHub()
    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    filed = await apply_carryover(github, "o", "r", plan)  # type: ignore[arg-type]

    assert [issue.fingerprint for issue in filed] == [_FP]
    assert github.labels_created == ["mergecraft-carryover"]
    created = github.created[0]
    assert created["labels"] == ["mergecraft-carryover"]
    assert finding_fingerprints_in(created["body"]) == frozenset({_FP})
    assert created["title"].startswith("[carryover #7] ")


async def test_sweeping_the_same_pr_twice_files_nothing_the_second_time() -> None:
    github = FakeGitHub()
    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]
    await apply_carryover(github, "o", "r", plan)  # type: ignore[arg-type]

    # The issue the first pass filed is now what the second pass reads back.
    github._issues = [{"number": 1, "body": github.created[0]["body"]}]
    second = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert second.to_file == []
    assert len(github.created) == 1


async def test_apply_writes_nothing_when_the_plan_is_empty() -> None:
    github = FakeGitHub(threads=[])
    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    assert await apply_carryover(github, "o", "r", plan) == []  # type: ignore[arg-type]
    assert github.labels_created == []


async def test_an_existing_label_is_not_an_error() -> None:
    github = FakeGitHub()
    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    async def _conflict(owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        raise _http_error(422)

    github.create_label = _conflict  # type: ignore[method-assign]

    assert len(await apply_carryover(github, "o", "r", plan)) == 1  # type: ignore[arg-type]


async def test_a_label_failure_that_is_not_a_conflict_surfaces() -> None:
    github = FakeGitHub()
    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]

    async def _forbidden(owner: str, repo: str, **kwargs: Any) -> dict[str, Any]:
        raise _http_error(403)

    github.create_label = _forbidden  # type: ignore[method-assign]

    with pytest.raises(httpx.HTTPStatusError):
        await apply_carryover(github, "o", "r", plan)  # type: ignore[arg-type]


async def test_one_unfilable_finding_does_not_strand_the_rest() -> None:
    github = FakeGitHub(
        threads=[_graphql_thread(node_id="T1"), _graphql_thread(node_id="T2", body=_OTHER)],
        create_issue_error=_http_error(500),
    )
    plan = await plan_carryover(github, "o", "r", 7)  # type: ignore[arg-type]
    assert {f.fingerprint for f in plan.to_file} == {_FP, _OTHER_FP}

    assert await apply_carryover(github, "o", "r", plan) == []  # type: ignore[arg-type]


async def test_fingerprint_read_stops_paginating_on_a_short_page() -> None:
    github = FakeGitHub(issues=[{"number": 5, "body": f"<!-- mergecraft-finding:v1:{_FP} -->"}])

    found = await filed_fingerprints(github, "o", "r")  # type: ignore[arg-type]

    assert found == frozenset({_FP})
    assert len(github.issue_pages) == 1
