"""Review metadata must never leak into the serialized GitHub request (#1131)."""

from __future__ import annotations

import copy
import json
from typing import Any

import httpx
import pytest

from mergecraft.utils.github import GitHubClient


@pytest.mark.parametrize(
    "anchor",
    [
        {"line": 20, "side": "RIGHT"},
        {"line": 20, "side": "LEFT", "start_line": 18, "start_side": "LEFT"},
        {"position": 6},
    ],
    ids=["single-line", "multi-line", "diff-position"],
)
async def test_create_review_serializes_only_accepted_comment_fields(
    anchor: dict[str, Any],
) -> None:
    body = "Finding.\n<!-- mergecraft-finding:abc -->"
    accepted = {"path": "src/app.py", "body": body, **anchor}
    payload = {
        "event": "REQUEST_CHANGES",
        "body": "Review body",
        "commit_id": "abc123",
        "comments": [
            {**accepted, "fingerprint": "abc", "collateral": ["src/other.py"]},
            {
                "path": "src/other.py",
                "body": "Another finding",
                "line": 12,
                "side": "RIGHT",
                "fingerprint": "def",
                "future_metadata": {"internal": True},
            },
        ],
    }
    original = copy.deepcopy(payload)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": 9})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as raw:
        result = await GitHubClient("t", client=raw).create_review("acme", "demo", 7, **payload)

    assert result == {"id": 9}
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert requests[0].url.path == "/repos/acme/demo/pulls/7/reviews"
    assert json.loads(requests[0].content) == {
        "event": "REQUEST_CHANGES",
        "body": "Review body",
        "commit_id": "abc123",
        "comments": [
            accepted,
            {
                "path": "src/other.py",
                "body": "Another finding",
                "line": 12,
                "side": "RIGHT",
            },
        ],
    }
    assert payload == original


@pytest.mark.parametrize("comments", [{}, {"comments": []}, {"comments": None}])
async def test_create_review_preserves_requests_without_inline_comments(
    comments: dict[str, Any],
) -> None:
    payload = {"event": "COMMENT", "body": "Review body", **comments}
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": 9})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.github.com"
    ) as raw:
        await GitHubClient("t", client=raw).create_review("acme", "demo", 7, **payload)

    assert len(requests) == 1
    assert json.loads(requests[0].content) == payload
