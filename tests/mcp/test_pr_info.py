"""``get_pull_request`` says when the closing-issues lookup failed.

"No closing issues" and "the lookup failed" used to render identically as
``closingIssues: []`` (a bare ``except Exception`` with no log). The tool now
catches narrowly, logs at warning, and returns ``closingIssuesUnavailable:
true`` beside the empty list, so the reviewing agent can tell the two apart.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from loguru import logger
from tests.support.tool_context import make_tool_context

from mergecraft.mcp.pr_info import get_pull_request_tool

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.scm.protocol import ScmProvider

_GREEN_AFTER_CLOSING_ISSUES_FLAG = pytest.mark.xfail(
    reason="green after VP4.5: a failed closing-issues lookup is logged and flagged",
    strict=False,
)

_PULL = {
    "number": 7,
    "html_url": "https://github.com/acme/demo/pull/7",
    "title": "Add widgets",
    "body": "Summary",
    "state": "open",
    "draft": False,
    "merged": False,
    "maintainer_can_modify": True,
    "head": {"ref": "feature/widgets", "repo": {"full_name": "acme/demo"}},
    "base": {"ref": "main", "repo": {"full_name": "acme/demo"}},
    "user": {"login": "dev1"},
    "assignees": [],
    "labels": [],
}


def _http_error(status: int) -> httpx.HTTPStatusError:
    request = httpx.Request("POST", "https://api.github.com/graphql")
    response = httpx.Response(status, request=request, json={"message": "Bad Gateway"})
    return httpx.HTTPStatusError(str(status), request=request, response=response)


class _PullScm:
    """Answers ``get_pull``; the closing-issues GraphQL call returns or raises as scripted."""

    def __init__(self, graphql: Any) -> None:
        self._graphql = graphql

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        del owner, repo, pull_number
        return dict(_PULL)

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        del query, variables
        if isinstance(self._graphql, BaseException):
            raise self._graphql
        return self._graphql


async def _get(tmp_path: Path, graphql: Any) -> tuple[dict[str, Any], list[str]]:
    ctx = make_tool_context(
        tmp_path, trust_tier="trusted", scm=cast("ScmProvider", _PullScm(graphql))
    )
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        result = await get_pull_request_tool(ctx).execute({"pull_number": 7})
    finally:
        logger.remove(sink_id)
    assert result.is_error is False, result.content[0]["text"]
    return cast("dict[str, Any]", json.loads(result.content[0]["text"])), captured


@_GREEN_AFTER_CLOSING_ISSUES_FLAG
@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(_http_error(502), id="http_502"),
        pytest.param(httpx.ConnectError("connection refused"), id="transport"),
    ],
)
async def test_a_failed_closing_issues_lookup_is_flagged_and_logged(
    tmp_path: Path, failure: BaseException
) -> None:
    payload, warnings = await _get(tmp_path, failure)

    assert payload["closingIssues"] == []
    assert payload["closingIssuesUnavailable"] is True
    assert warnings, "a swallowed lookup failure must be logged at warning"
    assert any("closing" in line.lower() for line in warnings)
    # The rest of the PR metadata is still returned.
    assert payload["number"] == 7
    assert payload["title"] == "Add widgets"


async def test_a_successful_lookup_lists_the_issues_and_is_not_flagged(tmp_path: Path) -> None:
    """Green guard: the happy path is unchanged and carries no unavailable flag."""
    graphql = {
        "repository": {
            "pullRequest": {"closingIssuesReferences": {"nodes": [{"number": 42, "title": "T"}]}}
        }
    }
    payload, warnings = await _get(tmp_path, graphql)

    assert payload["closingIssues"] == [{"number": 42, "title": "T"}]
    assert not payload.get("closingIssuesUnavailable")
    assert warnings == []


async def test_a_pr_with_no_closing_issues_is_not_flagged(tmp_path: Path) -> None:
    """Edge (green guard): an empty answer is a real "none", not a failure."""
    graphql: dict[str, Any] = {
        "repository": {"pullRequest": {"closingIssuesReferences": {"nodes": []}}}
    }
    payload, _warnings = await _get(tmp_path, graphql)

    assert payload["closingIssues"] == []
    assert not payload.get("closingIssuesUnavailable")


async def test_a_failure_fetching_the_pull_itself_is_still_an_error(tmp_path: Path) -> None:
    """Error (green guard): only the closing-issues half degrades; a failed PR read does not."""

    class _BrokenPullScm(_PullScm):
        async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
            raise _http_error(404)

    ctx = make_tool_context(
        tmp_path, trust_tier="trusted", scm=cast("ScmProvider", _BrokenPullScm({}))
    )
    result = await get_pull_request_tool(ctx).execute({"pull_number": 7})
    assert result.is_error is True
