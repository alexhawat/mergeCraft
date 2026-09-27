"""``get_issue_comments`` returns every page, or says it stopped early.

GitHub returns issue comments as a bare array, 100 at most per page, and ends
the listing with a short page. The tool pages with ``page``/``per_page=100``,
stops on a short page, stops at ``GITHUB_LIST_MAX_PAGES`` pages, and reports
``incomplete: true`` when it hit that cap instead of presenting the first
pages as "all comments".
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest
from tests.support.paged_scm import PagedListScm
from tests.support.tool_context import make_tool_context

from mergecraft.mcp.issue_comments import get_issue_comments_tool
from mergecraft.utils.github import GITHUB_LIST_MAX_PAGES

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.scm.protocol import ScmProvider

_GREEN_AFTER_PAGINATION = pytest.mark.xfail(
    reason="green after VP3.4: get_issue_comments paginates and reports incomplete",
    strict=False,
)


async def _list(tmp_path: Path, scm: PagedListScm) -> dict[str, Any]:
    ctx = make_tool_context(tmp_path, trust_tier="trusted", scm=cast("ScmProvider", scm))
    result = await get_issue_comments_tool(ctx).execute({"issue_number": 42})
    assert result.is_error is False, result.content[0]["text"]
    return cast("dict[str, Any]", json.loads(result.content[0]["text"]))


@_GREEN_AFTER_PAGINATION
async def test_250_comments_over_three_pages_come_back_complete(tmp_path: Path) -> None:
    scm = PagedListScm(total=250)
    payload = await _list(tmp_path, scm)

    assert payload["count"] == 250
    assert [comment["id"] for comment in payload["comments"]] == list(range(1, 251))
    assert scm.pages("comments") == [1, 2, 3]
    assert {request["per_page"] for request in scm.requests} == {100}
    assert not payload.get("incomplete")


@_GREEN_AFTER_PAGINATION
async def test_exactly_one_full_page_asks_once_more_and_stops_on_the_empty_page(
    tmp_path: Path,
) -> None:
    """Edge: a full last page is not proof of the end; the empty page is."""
    scm = PagedListScm(total=100)
    payload = await _list(tmp_path, scm)

    assert payload["count"] == 100
    assert scm.pages("comments") == [1, 2]
    assert not payload.get("incomplete")


@_GREEN_AFTER_PAGINATION
async def test_the_page_cap_stops_the_listing_and_says_incomplete(tmp_path: Path) -> None:
    """Error: a listing that never ends is capped, and the response says it was cut."""
    scm = PagedListScm(endless=True)
    payload = await _list(tmp_path, scm)

    assert scm.pages("comments") == list(range(1, GITHUB_LIST_MAX_PAGES + 1))
    assert payload["count"] == GITHUB_LIST_MAX_PAGES * 100
    assert payload["incomplete"] is True


async def test_a_short_first_page_is_one_request(tmp_path: Path) -> None:
    """Green guard: the common case stays one call and one complete answer."""
    scm = PagedListScm(total=3)
    payload = await _list(tmp_path, scm)

    assert payload["count"] == 3
    assert [comment["user"] for comment in payload["comments"]] == ["dev", "dev", "dev"]
    assert len(scm.requests) == 1
    assert scm.requests[0]["per_page"] == 100
    assert not payload.get("incomplete")


async def test_no_comments_is_an_empty_complete_listing(tmp_path: Path) -> None:
    """Edge (green guard): an issue with no comments."""
    scm = PagedListScm(total=0)
    payload = await _list(tmp_path, scm)

    assert payload["count"] == 0
    assert payload["comments"] == []
    assert not payload.get("incomplete")
