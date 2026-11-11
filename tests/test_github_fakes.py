"""Contract tests for the shared offline GitHub doubles."""

from __future__ import annotations

import json

import httpx
import pytest

from mergecraft.utils import token as token_mod
from tests.support.github_fakes import StrictGitHubClient, UnscriptedGitHubCall


@pytest.mark.parametrize(
    ("method", "path"),
    [("GET", "/app"), ("POST", "/app"), ("GET", "/repos/acme/demo")],
)
async def test_unscripted_request_raises_with_method_and_path(method: str, path: str) -> None:
    client = StrictGitHubClient()
    async with client._active_client():
        with pytest.raises(UnscriptedGitHubCall, match=f"unscripted GitHub call {method} {path}"):
            await client.request(method, path)

    assert client.unscripted_requests == [(method, path)]


@pytest.mark.parametrize("path", ["/app", "/app/", "/"])
async def test_scripted_json_route_returns_payload(path: str) -> None:
    payload = {"id": 42, "slug": "test-app"}
    client = StrictGitHubClient(routes={("get", path): payload})
    async with client._active_client():
        assert await client.get(path.rstrip("/") or "/") == payload
        assert await client.get(path) == payload
        with pytest.raises(UnscriptedGitHubCall, match="unscripted GitHub call POST"):
            await client.post(path)

    assert client.unscripted_requests == [("POST", path.rstrip("/") or "/")]


async def test_scripted_response_preserves_http_status() -> None:
    client = StrictGitHubClient(routes={("DELETE", "/installation/token"): httpx.Response(204)})
    async with client._active_client():
        assert await client.delete("/installation/token") is None
    assert client.unscripted_requests == []


@pytest.mark.parametrize("return_response", [False, True])
async def test_scripted_callable_receives_request_and_returns_answer(return_response: bool) -> None:
    requests: list[httpx.Request] = []

    def answer(request: httpx.Request) -> dict[str, str] | httpx.Response:
        requests.append(request)
        payload = {"body": json.loads(request.content)["body"]}
        return httpx.Response(201, json=payload) if return_response else payload

    path = "/repos/acme/demo/issues/7/comments"
    client = StrictGitHubClient(routes={("POST", path): answer})
    async with client._active_client():
        result = await client.create_issue_comment("acme", "demo", 7, "review comment")

    assert result == {"body": "review comment"}
    assert [(request.method, request.url.path) for request in requests] == [("POST", path)]
    assert client.unscripted_requests == []


async def test_offline_token_revoke_records_both_entry_points(
    offline_token_revoke: list[str],
) -> None:
    assert offline_token_revoke == []
    await token_mod.revoke_installation_token("first-test-token")
    await token_mod.revoke_github_installation_token("second-test-token")
    await token_mod.revoke_installation_token("first-test-token")
    assert offline_token_revoke == ["first-test-token", "second-test-token", "first-test-token"]
