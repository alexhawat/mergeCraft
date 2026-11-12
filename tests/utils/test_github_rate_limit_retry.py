"""GitHub client retries: read-only GraphQL, rate-limit 403s and ``Retry-After``.

Driven through the real ``GitHubClient`` over an ``httpx.MockTransport``. The
retry sleep is replaced with a recorder so the waits the client asks for are
observable without spending wall-clock time.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mergecraft.utils import github as github_mod
from mergecraft.utils.github import GitHubClient


@pytest.fixture
def waits(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    recorded: list[float] = []

    async def _record(seconds: float) -> None:
        recorded.append(seconds)

    # ``GitHubClient._send`` copies its retry controller per call, sleep included.
    monkeypatch.setattr(GitHubClient._send.retry, "sleep", _record)  # type: ignore[attr-defined]
    return recorded


def _client(responses: list[httpx.Response]) -> tuple[GitHubClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def _handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return responses[min(len(seen), len(responses)) - 1]

    transport = httpx.MockTransport(_handler)
    http = httpx.AsyncClient(base_url="https://api.github.test", transport=transport)
    return GitHubClient(token="t", base_url="https://api.github.test", client=http), seen


def _ok_graphql() -> httpx.Response:
    return httpx.Response(200, json={"data": {"viewer": {"login": "octo"}}})


def _rate_limited(**headers: str) -> httpx.Response:
    return httpx.Response(
        403, headers=headers, json={"message": "API rate limit exceeded for installation"}
    )


async def test_a_read_only_graphql_query_is_retried_after_a_502(waits: list[float]) -> None:
    client, seen = _client([httpx.Response(502), _ok_graphql()])

    data = await client.graphql("query { viewer { login } }")

    assert data == {"viewer": {"login": "octo"}}
    assert len(seen) == 2
    assert len(waits) == 1


async def test_a_graphql_mutation_is_not_retried(waits: list[float]) -> None:
    client, seen = _client([httpx.Response(502), _ok_graphql()])

    with pytest.raises(httpx.HTTPStatusError):
        await client.graphql('mutation { resolveReviewThread(input: {threadId: "T"}) { x } }')

    assert len(seen) == 1
    assert waits == []


async def test_a_403_with_retry_after_is_retried_after_that_wait(waits: list[float]) -> None:
    client, seen = _client([_rate_limited(**{"retry-after": "7"}), httpx.Response(200, json={})])

    await client.get("/repos/acme/demo")

    assert len(seen) == 2
    assert waits == [7.0]


async def test_a_primary_rate_limit_waits_until_the_reset(
    waits: list[float], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(github_mod.time, "time", lambda: 1_000.0)
    client, seen = _client(
        [
            _rate_limited(**{"x-ratelimit-remaining": "0", "x-ratelimit-reset": "1012"}),
            httpx.Response(200, json={}),
        ]
    )

    await client.get("/repos/acme/demo")

    assert len(seen) == 2
    assert waits == [12.0]


async def test_a_secondary_rate_limit_message_is_retried(waits: list[float]) -> None:
    secondary = httpx.Response(
        403, json={"message": "You have exceeded a secondary rate limit. Please wait."}
    )
    client, seen = _client([secondary, httpx.Response(200, json={})])

    await client.get("/repos/acme/demo")

    assert len(seen) == 2
    assert len(waits) == 1


async def test_a_retry_after_wait_is_capped(waits: list[float]) -> None:
    client, _seen = _client([_rate_limited(**{"retry-after": "86400"}), _ok_graphql()])

    await client.graphql("query { viewer { login } }")

    assert waits == [github_mod.RATE_LIMIT_MAX_WAIT_S]


async def test_a_plain_permission_403_is_not_retried(waits: list[float]) -> None:
    forbidden = httpx.Response(403, json={"message": "Resource not accessible by integration"})
    client, seen = _client([forbidden, httpx.Response(200, json={})])

    with pytest.raises(httpx.HTTPStatusError):
        await client.get("/repos/acme/demo")

    assert len(seen) == 1
    assert waits == []


async def test_a_rate_limited_rest_mutation_is_not_retried(waits: list[float]) -> None:
    client, seen = _client([_rate_limited(**{"retry-after": "1"}), httpx.Response(201, json={})])

    with pytest.raises(httpx.HTTPStatusError):
        await client.post("/repos/acme/demo/issues", json={"title": "x"})

    assert len(seen) == 1


async def test_the_retried_graphql_request_is_the_same_query(waits: list[float]) -> None:
    client, seen = _client([httpx.Response(503), _ok_graphql()])
    variables = {"owner": "acme"}

    await client.graphql("query($owner: String!) { x }", variables)

    bodies: list[dict[str, Any]] = [json.loads(request.content) for request in seen]
    expected = {"query": "query($owner: String!) { x }", "variables": variables}
    assert bodies == [expected, expected]
