"""Tests for GitHub client + local run-context assembly."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from mergecraft.config.settings import default_settings
from mergecraft.utils.github import (
    DEFAULT_API_URL,
    GitHubClient,
    _default_api_base_url,
    parse_repo_context,
    resolve_run_context_data,
)


def test_default_api_base_url_falls_back_to_public_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W11 — ``_default_api_base_url`` defaults to api.github.com when unset."""
    monkeypatch.delenv("GITHUB_API_URL", raising=False)
    assert _default_api_base_url() == DEFAULT_API_URL


def test_default_api_base_url_honours_github_api_url_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W11 / D6 — GHES and E2E mock point GitHubClient via ``GITHUB_API_URL``."""
    monkeypatch.setenv("GITHUB_API_URL", "http://127.0.0.1:9/api/v3/")
    assert _default_api_base_url() == "http://127.0.0.1:9/api/v3"


@pytest.mark.asyncio
async def test_github_client_uses_default_api_base_url_when_base_url_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_API_URL", "https://github.example.test/api/v3")
    client = GitHubClient("t")
    try:
        assert client.base_url == "https://github.example.test/api/v3"
    finally:
        await client.aclose()


def test_parse_repo_context(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widgets")
    ctx = parse_repo_context()
    assert ctx.owner == "acme"
    assert ctx.name == "widgets"

    monkeypatch.delenv("GITHUB_REPOSITORY")
    with pytest.raises(ValueError, match="required"):
        parse_repo_context()

    with pytest.raises(ValueError, match="Invalid"):
        parse_repo_context("nonsplit")


@pytest.mark.asyncio
async def test_github_client_rest_helpers() -> None:
    calls: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        path = request.url.path
        if path == "/repos/acme/widgets":
            return httpx.Response(200, json={"full_name": "acme/widgets", "private": False})
        if path.endswith("/issues/1"):
            return httpx.Response(200, json={"number": 1, "title": "hi"})
        if path.endswith("/issues/1/comments"):
            return httpx.Response(200, json=[{"id": 9, "body": "c"}])
        if path.endswith("/pulls/2"):
            return httpx.Response(200, json={"number": 2})
        if path.endswith("/pulls/2/reviews"):
            return httpx.Response(200, json=[{"id": 3}])
        if path.endswith("/statuses/abc"):
            return httpx.Response(201, json={"state": "success"})
        if path.endswith("/check-suites"):
            return httpx.Response(200, json={"total_count": 0, "check_suites": []})
        if path == "/graphql":
            return httpx.Response(200, json={"data": {"viewer": {"login": "bot"}}})
        return httpx.Response(404, json={"message": "nope"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://api.github.com",
        headers={"Authorization": "Bearer t"},
    ) as raw:
        client = GitHubClient("t", client=raw)
        repo = await client.get_repo("acme", "widgets")
        assert repo["full_name"] == "acme/widgets"
        issue = await client.get_issue("acme", "widgets", 1)
        assert issue["number"] == 1
        comments = await client.list_issue_comments("acme", "widgets", 1)
        assert comments[0]["id"] == 9
        pr = await client.get_pull("acme", "widgets", 2)
        assert pr["number"] == 2
        reviews = await client.list_reviews("acme", "widgets", 2)
        assert reviews[0]["id"] == 3
        status = await client.create_status(
            "acme", "widgets", "abc", state="success", context="mergecraft"
        )
        assert status["state"] == "success"
        suites = await client.list_check_suites_for_ref("acme", "widgets", "main")
        assert suites["total_count"] == 0
        gql = await client.graphql("query { viewer { login } }")
        assert gql["viewer"]["login"] == "bot"

    assert ("GET", "/repos/acme/widgets") in calls
    assert ("POST", "/graphql") in calls


@pytest.mark.asyncio
async def test_resolve_run_context_data_local_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_REPOSITORY", "acme/widgets")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/acme/widgets"
        return httpx.Response(
            200,
            json={"full_name": "acme/widgets", "private": True, "default_branch": "main"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://api.github.com",
        headers={"Authorization": "Bearer t"},
    ) as raw:
        client = GitHubClient("t", client=raw)
        ctx = await resolve_run_context_data(client, settings=default_settings())

    assert ctx.repo.owner == "acme"
    assert ctx.repo.name == "widgets"
    assert ctx.repo.data["private"] is True
    assert ctx.oss is False
    assert ctx.api_token == ""
    assert ctx.plan == "none"
    assert ctx.proxy_model is None
    assert ctx.db_secrets is None
    assert ctx.repo_settings.push == "restricted"


@pytest.mark.asyncio
async def test_graphql_errors_raise() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"errors": [{"message": "boom"}]})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        with pytest.raises(RuntimeError, match="GraphQL"):
            await client.graphql("query { x }")


@pytest.mark.asyncio
async def test_list_workflow_run_artifacts_follows_pages() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/actions/runs/9/artifacts")
        page = int(request.url.params.get("page") or "1")
        pages.append(page)
        if page == 1:
            artifacts = [{"id": i, "name": f"a{i}"} for i in range(100)]
        else:
            artifacts = [{"id": 100, "name": "last"}]
        return httpx.Response(200, json={"total_count": 101, "artifacts": artifacts})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        artifacts = await client.list_workflow_run_artifacts("acme", "widgets", 9)

    assert pages == [1, 2]
    assert len(artifacts.items) == 101
    assert artifacts.incomplete is False
    assert artifacts.total_count == 101
    assert artifacts.items[-1]["name"] == "last"


@pytest.mark.asyncio
async def test_list_check_runs_for_ref_follows_pages() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/commits/abc/check-runs")
        page = int(request.url.params.get("page") or "1")
        pages.append(page)
        if page == 1:
            runs = [{"id": i, "name": f"c{i}"} for i in range(100)]
        else:
            runs = [{"id": 100, "name": "last"}]
        return httpx.Response(200, json={"total_count": 101, "check_runs": runs})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        payload = await client.list_check_runs_for_ref("acme", "widgets", "abc")

    assert pages == [1, 2]
    assert payload.total_count == 101
    assert payload.incomplete is False
    assert payload.items[-1]["name"] == "last"


@pytest.mark.asyncio
async def test_list_workflow_runs_for_check_suite_follows_pages() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/actions/runs")
        assert request.url.params.get("check_suite_id") == "7"
        page = int(request.url.params.get("page") or "1")
        pages.append(page)
        runs = [{"id": i} for i in range(100)] if page == 1 else [{"id": 100}]
        return httpx.Response(200, json={"total_count": 101, "workflow_runs": runs})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        runs = await client.list_workflow_runs_for_check_suite("acme", "widgets", 7)

    assert pages == [1, 2]
    assert len(runs.items) == 101
    assert runs.incomplete is False
    assert runs.total_count == 101


@pytest.mark.asyncio
async def test_paginate_logs_when_max_pages_is_full() -> None:
    from loguru import logger

    from mergecraft.utils.github import paginate_github_list_pages

    async def _full(_page: int) -> dict[str, object]:
        return {"items": [{"id": 1}, {"id": 2}]}

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message.record["message"])))
    try:
        listed = await paginate_github_list_pages(_full, item_key="items", page_size=2, max_pages=1)
    finally:
        logger.remove(sink_id)
    assert len(listed.items) == 2
    assert listed.incomplete is True
    assert any("max_pages" in item for item in messages)


@pytest.mark.asyncio
async def test_paginate_logs_unexpected_non_object_payload() -> None:
    from loguru import logger

    from mergecraft.utils.github import paginate_github_list_pages

    async def _weird(_page: int) -> str:
        return "nope"

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message.record["message"])))
    try:
        listed = await paginate_github_list_pages(_weird, item_key="items", page_size=100)
    finally:
        logger.remove(sink_id)
        assert listed.items == []
        assert listed.incomplete is True
        assert any("unexpected" in item for item in messages)
        assert not any("end of list" in item for item in messages)
        assert any("without treating the list as complete" in item for item in messages)


@pytest.mark.asyncio
async def test_paginate_object_missing_item_key_is_incomplete() -> None:
    from mergecraft.utils.github import paginate_github_list_pages

    async def _missing(_page: int) -> dict[str, object]:
        return {"total_count": 0}

    listed = await paginate_github_list_pages(_missing, item_key="workflow_runs", page_size=100)
    assert listed.items == []
    assert listed.incomplete is True
    assert listed.total_count == 0


@pytest.mark.asyncio
async def test_paginate_array_page_is_incomplete_when_object_expected() -> None:
    from mergecraft.utils.github import paginate_github_list_pages

    async def _array(_page: int) -> list[dict[str, object]]:
        return [{"id": 1}]

    listed = await paginate_github_list_pages(_array, item_key="artifacts", page_size=100)
    assert listed.items == []
    assert listed.incomplete is True


@pytest.mark.asyncio
async def test_paginate_non_list_item_key_is_incomplete() -> None:
    from mergecraft.utils.github import paginate_github_list_pages

    async def _string(_page: int) -> dict[str, object]:
        return {"artifacts": "nope"}

    listed = await paginate_github_list_pages(_string, item_key="artifacts", page_size=100)
    assert listed.items == []
    assert listed.incomplete is True


@pytest.mark.asyncio
async def test_paginate_mixed_non_dict_rows_is_incomplete() -> None:
    from mergecraft.utils.github import paginate_github_list_pages

    async def _mixed(_page: int) -> dict[str, object]:
        return {"check_runs": [{"id": 1}, "skip", {"id": 2}]}

    listed = await paginate_github_list_pages(_mixed, item_key="check_runs", page_size=100)
    assert [row["id"] for row in listed.items] == [1, 2]
    assert listed.incomplete is True


def test_require_github_listed_rejects_bare_list() -> None:
    from mergecraft.utils.github import require_github_listed

    with pytest.raises(TypeError, match="ListedItems"):
        require_github_listed([{"id": 1}])


@pytest.mark.asyncio
async def test_list_issue_comments_rejects_non_array_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/issues/1/comments")
        return httpx.Response(200, json={"message": "not a list"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        with pytest.raises(TypeError, match="JSON array"):
            await client.list_issue_comments("acme", "widgets", 1)


@pytest.mark.asyncio
async def test_list_check_runs_for_ref_keeps_api_total_when_walk_is_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncated walk must not overwrite GitHub's total_count with len(runs)."""
    from mergecraft.utils import github as github_mod

    async def _truncated(
        fetch_page: Any,
        **_kwargs: Any,
    ) -> github_mod.GitHubListedItems:
        payload = await fetch_page(1)
        assert isinstance(payload, dict)
        runs = payload["check_runs"]
        assert isinstance(runs, list)
        return github_mod.GitHubListedItems(items=runs, incomplete=True, total_count=500)

    monkeypatch.setattr(github_mod, "paginate_github_list_pages", _truncated)

    def handler(request: httpx.Request) -> httpx.Response:
        _ = request
        runs = [{"id": i, "name": f"c{i}"} for i in range(3)]
        return httpx.Response(200, json={"total_count": 500, "check_runs": runs})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as raw:
        client = GitHubClient("t", client=raw)
        payload = await client.list_check_runs_for_ref("acme", "widgets", "abc")

    assert payload.incomplete is True
    assert payload.total_count == 500
    assert len(payload.items) == 3
    assert payload.total_count != len(payload.items)


def test_provider_agents_import_failure_taxonomy_from_provider_failure() -> None:
    from mergecraft.agents import claude, codex, gemini, opencode
    from mergecraft.utils.provider_failure import is_retryable_cli_failure

    for module in (claude, codex, gemini, opencode):
        assert module.is_retryable_cli_failure is is_retryable_cli_failure
