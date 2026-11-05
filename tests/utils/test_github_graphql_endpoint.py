"""REST and GraphQL use different endpoint roots on GitHub Enterprise."""

from __future__ import annotations

import json

import httpx
import pytest

from mergecraft.utils.github import GitHubClient


@pytest.mark.parametrize(
    ("api_url", "graphql_env", "expected"),
    [
        ("https://api.github.com", None, "https://api.github.com/graphql"),
        ("https://ghe.example/api/v3/", None, "https://ghe.example/api/graphql"),
        ("http://localhost:9000", None, "http://localhost:9000/graphql"),
        ("https://proxy.example/github/api/v3", None, "https://proxy.example/github/api/graphql"),
        (
            "https://ghe.example/api/v3",
            "https://ghe.example/custom/graphql",
            "https://ghe.example/custom/graphql",
        ),
    ],
)
async def test_graphql_endpoint_is_independent_of_rest_prefix(
    monkeypatch: pytest.MonkeyPatch, api_url: str, graphql_env: str | None, expected: str
) -> None:
    monkeypatch.setenv("GITHUB_API_URL", api_url)
    monkeypatch.delenv("GITHUB_GRAPHQL_URL", raising=False)
    if graphql_env:
        monkeypatch.setenv("GITHUB_GRAPHQL_URL", graphql_env)
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"data": {"viewer": {"login": "bot"}}})

    async with httpx.AsyncClient(base_url=api_url, transport=httpx.MockTransport(handler)) as raw:
        client = GitHubClient("test-token", client=raw)
        assert await client.graphql("query($n:Int!){viewer{login}}", {"n": 7}) == {
            "viewer": {"login": "bot"}
        }
        await client.get("/repos/acme/repo")

    assert str(calls[0].url) == expected
    assert json.loads(calls[0].content)["variables"] == {"n": 7}
    assert str(calls[1].url) == api_url.rstrip("/") + "/repos/acme/repo"


async def test_explicit_rest_url_does_not_inherit_other_server_graphql_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_GRAPHQL_URL", "https://ambient.example/api/graphql")
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": {}})

    async with httpx.AsyncClient(
        base_url="https://explicit.example/api/v3", transport=httpx.MockTransport(handler)
    ) as raw:
        client = GitHubClient("test-token", base_url="https://explicit.example/api/v3", client=raw)
        await client.graphql("query { viewer { login } }")

    assert calls == ["https://explicit.example/api/graphql"]


async def test_explicit_graphql_endpoint_overrides_derivation() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, json={"data": {}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as raw:
        client = GitHubClient(
            "test-token",
            base_url="https://ghe.example/api/v3",
            graphql_url="https://ghe.example/proxy/graphql",
            client=raw,
        )
        await client.graphql("query { viewer { login } }")

    assert calls == ["https://ghe.example/proxy/graphql"]
