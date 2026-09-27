"""``list_pull_request_reviews`` returns every page, or says it stopped early.

GitHub lists a pull request's reviews **oldest first**, so a single page of 100
drops the *newest* reviews — exactly the ones an incremental re-review needs.
The tool pages with ``page``/``per_page=100``, stops on a short page, stops at
``GITHUB_LIST_MAX_PAGES`` pages, and reports ``incomplete: true`` at the cap.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

import pytest
from tests.support.paged_scm import PagedListScm
from tests.support.tool_context import make_tool_context

from mergecraft.mcp.review_comments import list_pull_request_reviews_tool
from mergecraft.utils.github import GITHUB_LIST_MAX_PAGES

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.scm.protocol import ScmProvider

_GREEN_AFTER_PAGINATION = pytest.mark.xfail(
    reason="green after VP3.5: list_pull_request_reviews paginates and reports incomplete",
    strict=False,
)


async def _list(tmp_path: Path, scm: PagedListScm) -> dict[str, Any]:
    ctx = make_tool_context(tmp_path, trust_tier="trusted", scm=cast("ScmProvider", scm))
    result = await list_pull_request_reviews_tool(ctx).execute({"pull_number": 7})
    assert result.is_error is False, result.content[0]["text"]
    return cast("dict[str, Any]", json.loads(result.content[0]["text"]))


@_GREEN_AFTER_PAGINATION
async def test_more_than_100_reviews_include_the_newest(tmp_path: Path) -> None:
    scm = PagedListScm(total=150)
    payload = await _list(tmp_path, scm)

    ids = [review["id"] for review in payload["reviews"]]
    assert 150 in ids, "the newest review was cut off by the first page"
    assert ids == list(range(1, 151))
    assert payload["count"] == 150
    assert scm.pages("reviews") == [1, 2]
    assert not payload.get("incomplete")


@_GREEN_AFTER_PAGINATION
async def test_the_page_cap_stops_the_listing_and_says_incomplete(tmp_path: Path) -> None:
    scm = PagedListScm(endless=True)
    payload = await _list(tmp_path, scm)

    assert scm.pages("reviews") == list(range(1, GITHUB_LIST_MAX_PAGES + 1))
    assert payload["count"] == GITHUB_LIST_MAX_PAGES * 100
    assert payload["incomplete"] is True


async def test_a_short_first_page_is_one_request_with_the_same_row_shape(tmp_path: Path) -> None:
    """Green guard: one call, and each row keeps its fields."""
    scm = PagedListScm(total=2)
    payload = await _list(tmp_path, scm)

    assert len(scm.requests) == 1
    assert scm.requests[0]["per_page"] == 100
    assert payload["count"] == 2
    first = payload["reviews"][0]
    assert first["id"] == 1
    assert first["user"] == "reviewer"
    assert first["state"] == "COMMENTED"
    assert first["commit_id"] == f"{1:040d}"
    assert set(first) >= {"id", "state", "body", "user", "submitted_at", "commit_id"}
    assert not payload.get("incomplete")
