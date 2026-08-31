"""B1 GitHub list pagination contracts (green after TP2)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from loguru import logger

from mergecraft.mcp.checkout import last_reviewed_sha
from mergecraft.utils.github import GitHubClient

_OWNER = "acme"
_REPO = "widgets"
_MERGECRAFT_BODY = "### Review\n\n---\n*via mergecraft*"
_HEAD_SHA = "f" * 40
_TARGET_COMMIT = "c" * 40


def _page_items(page: int, *, page_size: int = 100) -> list[dict[str, Any]]:
    if page <= 2:
        start = (page - 1) * page_size
        return [{"id": start + offset, "seq": start + offset} for offset in range(page_size)]
    if page == 3:
        return [{"id": 200, "seq": 200}]
    return []


def _array_handler(path_suffix: str) -> Callable[[httpx.Request], httpx.Response]:
    pages_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(path_suffix)
        page = int(request.url.params.get("page") or "1")
        pages_seen.append(page)
        return httpx.Response(200, json=_page_items(page))

    handler.pages_seen = pages_seen  # type: ignore[attr-defined]
    return handler


def _wrapped_handler(
    path_suffix: str,
    *,
    item_key: str,
    total_count: int = 201,
) -> Callable[[httpx.Request], httpx.Response]:
    pages_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith(path_suffix)
        page = int(request.url.params.get("page") or "1")
        pages_seen.append(page)
        return httpx.Response(
            200,
            json={"total_count": total_count, item_key: _page_items(page)},
        )

    handler.pages_seen = pages_seen  # type: ignore[attr-defined]
    return handler


def _review_handler_for_last_reviewed_sha() -> Callable[[httpx.Request], httpx.Response]:
    pages_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/pulls/2/reviews")
        page = int(request.url.params.get("page") or "1")
        pages_seen.append(page)
        if page <= 2:
            reviews = [
                {"id": (page - 1) * 100 + offset, "commit_id": "a" * 40, "body": "human review"}
                for offset in range(100)
            ]
        elif page == 3:
            reviews = [
                {
                    "id": 200,
                    "commit_id": _TARGET_COMMIT,
                    "body": _MERGECRAFT_BODY,
                }
            ]
        else:
            reviews = []
        return httpx.Response(200, json=reviews)

    handler.pages_seen = pages_seen  # type: ignore[attr-defined]
    return handler


@pytest.mark.asyncio
async def test_list_reviews_concatenates_three_pages_in_order() -> None:
    reviews_handler = _array_handler("/pulls/2/reviews")
    transport = httpx.MockTransport(reviews_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        reviews = await client.list_reviews(_OWNER, _REPO, 2)

    assert reviews_handler.pages_seen == [1, 2, 3]  # type: ignore[attr-defined]
    assert len(reviews) == 201
    assert [row["seq"] for row in reviews] == list(range(201))


@pytest.mark.asyncio
async def test_list_issue_comments_concatenates_three_pages_in_order() -> None:
    comments_handler = _array_handler("/issues/1/comments")
    transport = httpx.MockTransport(comments_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        comments = await client.list_issue_comments(_OWNER, _REPO, 1)

    assert comments_handler.pages_seen == [1, 2, 3]  # type: ignore[attr-defined]
    assert len(comments) == 201
    assert [row["seq"] for row in comments] == list(range(201))


@pytest.mark.asyncio
async def test_list_pull_files_concatenates_three_pages_in_order() -> None:
    files_handler = _array_handler("/pulls/2/files")
    transport = httpx.MockTransport(files_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        files = await client.list_pull_files(_OWNER, _REPO, 2)

    assert files_handler.pages_seen == [1, 2, 3]  # type: ignore[attr-defined]
    assert len(files) == 201
    assert [row["seq"] for row in files] == list(range(201))


@pytest.mark.asyncio
async def test_list_check_runs_for_ref_concatenates_three_pages_preserves_total_count() -> None:
    runs_handler = _wrapped_handler("/commits/abc/check-runs", item_key="check_runs")
    transport = httpx.MockTransport(runs_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        payload = await client.list_check_runs_for_ref(_OWNER, _REPO, "abc")

    assert runs_handler.pages_seen == [1, 2, 3]  # type: ignore[attr-defined]
    assert len(payload.items) == 201
    assert [row["seq"] for row in payload.items] == list(range(201))
    assert payload.total_count == 201


@pytest.mark.asyncio
async def test_list_workflow_run_artifacts_concatenates_three_pages() -> None:
    artifacts_handler = _wrapped_handler(
        "/actions/runs/9/artifacts",
        item_key="artifacts",
    )
    transport = httpx.MockTransport(artifacts_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        artifacts = await client.list_workflow_run_artifacts(_OWNER, _REPO, 9)

    assert artifacts_handler.pages_seen == [1, 2, 3]  # type: ignore[attr-defined]
    assert len(artifacts.items) == 201
    assert [row["seq"] for row in artifacts.items] == list(range(201))
    assert artifacts.total_count == 201


@pytest.mark.asyncio
async def test_list_issues_with_page_param_issues_single_get() -> None:
    request_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_count
        assert request.url.path.endswith("/issues")
        request_count += 1
        return httpx.Response(200, json=[{"number": 1, "title": "only page"}])

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        issues = await client.list_issues(
            _OWNER,
            _REPO,
            params={"page": 1, "per_page": 100},
        )

    assert request_count == 1
    assert len(issues) == 1
    assert issues[0]["number"] == 1


@pytest.mark.asyncio
async def test_list_reviews_stops_at_fifty_pages_and_logs_truncation_warning() -> None:
    pages_seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page") or "1")
        pages_seen.append(page)
        start = (page - 1) * 100
        return httpx.Response(
            200,
            json=[{"id": start + offset} for offset in range(100)],
        )

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message.record["message"])))
    transport = httpx.MockTransport(handler)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
            client = GitHubClient("t", client=raw)
            reviews = await client.list_reviews(_OWNER, _REPO, 2)
    finally:
        logger.remove(sink_id)

    assert 51 not in pages_seen
    assert max(pages_seen) == 50
    assert len(reviews) == 5000
    assert any("truncated" in message.lower() for message in messages)


@pytest.mark.asyncio
async def test_last_reviewed_sha_returns_newest_mergecraft_review_from_page_three() -> None:
    reviews_handler = _review_handler_for_last_reviewed_sha()
    transport = httpx.MockTransport(reviews_handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        reviews = await client.list_reviews(_OWNER, _REPO, 2)

    assert reviews_handler.pages_seen == [1, 2, 3]  # type: ignore[attr-defined]
    assert len(reviews) == 201
    assert last_reviewed_sha(reviews, head_sha=_HEAD_SHA) == _TARGET_COMMIT

    # Guard deletion: a single-page walk never sees the newest mergeCraft review.
    first_page_only = reviews[:100]
    assert last_reviewed_sha(first_page_only, head_sha=_HEAD_SHA) is None
