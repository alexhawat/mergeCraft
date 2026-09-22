"""Behavioral suite for ``integrations/cursor_cloud/client.py`` (#13, plan 29 T3).

The client had **zero** importers under ``tests/``. These tests drive it
against a fake ``httpx.AsyncClient.request`` and assert what the client does:
request/auth shaping, non-2xx handling, non-JSON bodies, payload construction,
artifact filtering, and the retry boundary (reads retry on 429/5xx/transport;
mutations never retry).
"""

from __future__ import annotations

import base64
import re
from typing import Any

import httpx
import pytest
import tenacity

from mergecraft.integrations.cursor_cloud.client import (
    CURSOR_API_KEY_ENV,
    CursorCloudClient,
    resolve_cursor_api_key,
)

_URL = "https://api.cursor.com/v1/x"


class _Transport:
    """Callable stand-in for ``httpx.AsyncClient.request``; records each call."""

    def __init__(self, *responses: Any) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"method": method, "url": url, **kwargs})
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        item = self._responses[index]
        if isinstance(item, BaseException):
            raise item
        return item


def _response(status: int, **kwargs: Any) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("GET", _URL), **kwargs)


def _patch_transport(monkeypatch: pytest.MonkeyPatch, transport: _Transport) -> None:
    monkeypatch.setattr(httpx.AsyncClient, "request", transport)


@pytest.fixture
def fast_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Zero the tenacity backoff so retry-exhaustion tests do not sleep."""
    monkeypatch.setattr(CursorCloudClient._request.retry, "wait", tenacity.wait_fixed(0))


def _client() -> CursorCloudClient:
    return CursorCloudClient(api_key="secret-key")


# ── environment / auth ─────────────────────────────────────────────────


def test_resolve_cursor_api_key_reads_and_strips_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(CURSOR_API_KEY_ENV, raising=False)
    assert resolve_cursor_api_key() is None

    monkeypatch.setenv(CURSOR_API_KEY_ENV, "  key-123  ")
    assert resolve_cursor_api_key() == "key-123"

    monkeypatch.setenv(CURSOR_API_KEY_ENV, "   ")
    assert resolve_cursor_api_key() is None


@pytest.mark.asyncio
async def test_request_sends_basic_auth_and_returns_object(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(200, json={"ok": True}))
    _patch_transport(monkeypatch, transport)

    data = await _client()._request(method="GET", path="/v1/agents")

    assert data == {"ok": True}
    assert len(transport.calls) == 1
    assert transport.calls[0]["method"] == "GET"
    assert transport.calls[0]["url"] == "https://api.cursor.com/v1/agents"
    token = transport.calls[0]["headers"]["Authorization"].removeprefix("Basic ")
    assert base64.b64decode(token).decode("ascii") == "secret-key:"


# ── error handling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_permanent_4xx_raises_runtime_error_with_detail(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(404, json={"detail": "run not found"}))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="cursor API error 404: run not found"):
        await _client()._request(method="GET", path="/v1/agents/a/runs/r")

    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_error_uses_message_field_when_detail_absent(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(401, json={"message": "bad key"}))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="cursor API error 401: bad key"):
        await _client()._request(method="GET", path="/v1/agents")


@pytest.mark.asyncio
async def test_error_falls_back_to_the_full_body(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(422, json={"errors": ["nope"]}))
    _patch_transport(monkeypatch, transport)
    expected = re.escape("cursor API error 422: {'errors': ['nope']}")

    with pytest.raises(RuntimeError, match=expected):
        await _client()._request(method="GET", path="/v1/agents")


@pytest.mark.asyncio
async def test_non_json_body_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(200, text="<html>not json</html>"))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="cursor returned non-JSON"):
        await _client()._request(method="GET", path="/v1/agents")


@pytest.mark.asyncio
async def test_non_object_json_raises_runtime_error(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(200, json=[1, 2, 3]))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="cursor returned non-object JSON"):
        await _client()._request(method="GET", path="/v1/agents")


# ── retry boundary ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mutation_5xx_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    """A POST that failed with 5xx may have landed; retrying is unsafe."""
    transport = _Transport(_response(500, json={"detail": "boom"}))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="cursor API error 500: boom"):
        await _client()._request(method="POST", path="/v1/agents", json_body={"x": 1})

    assert len(transport.calls) == 1, f"mutation retried {len(transport.calls) - 1} time(s)"


@pytest.mark.asyncio
async def test_read_5xx_retries_to_exhaustion(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(_response(503, json={"detail": "unavailable"}))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(httpx.HTTPStatusError):
        await _client()._request(method="GET", path="/v1/agents/a/runs/r")

    assert len(transport.calls) == 3


@pytest.mark.asyncio
async def test_mutation_transport_error_is_not_retried(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(httpx.ReadTimeout("timed out"))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(RuntimeError, match="cursor upstream failed"):
        await _client()._request(method="POST", path="/v1/agents", json_body={})

    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_read_timeout_retries_to_exhaustion(
    monkeypatch: pytest.MonkeyPatch, fast_retry: None
) -> None:
    transport = _Transport(httpx.ReadTimeout("timed out"))
    _patch_transport(monkeypatch, transport)

    with pytest.raises(httpx.ReadTimeout):
        await _client()._request(method="GET", path="/v1/agents/a/runs/r")

    assert len(transport.calls) == 3


# ── payload shaping ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_cloud_agent_shapes_payload_and_returns_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def _fake_request(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "agent": {"id": "agent-1", "url": "https://cursor.com/agents/agent-1"},
            "run": {"id": "run-1"},
        }

    client = _client()
    monkeypatch.setattr(client, "_request", _fake_request)

    result = await client.create_cloud_agent(
        prompt="review this",
        repo_url="https://github.com/acme/demo",
        starting_ref="release",
        model="composer-2",
        auto_create_pr=True,
        mcp_servers=[{"url": "https://mcp.example"}],
    )

    assert result == {
        "id": "run-1",
        "agent_id": "agent-1",
        "run_id": "run-1",
        "dashboard_url": "https://cursor.com/agents/agent-1",
    }
    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/agents"
    body = captured["json_body"]
    assert body["prompt"] == {"text": "review this"}
    assert body["repos"] == [{"url": "https://github.com/acme/demo", "startingRef": "release"}]
    assert body["model"] == {"id": "composer-2"}
    assert body["autoCreatePR"] is True
    assert body["mcpServers"] == [{"url": "https://mcp.example"}]


@pytest.mark.asyncio
async def test_create_cloud_agent_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    async def _fake_request(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"id": "agent-x"}

    client = _client()
    monkeypatch.setattr(client, "_request", _fake_request)

    result = await client.create_cloud_agent(prompt="p", repo_url="u")

    assert result["id"] == "agent-x"
    assert result["agent_id"] == "agent-x"
    assert result["run_id"] == "agent-x"
    body = captured["json_body"]
    assert body["repos"] == [{"url": "u", "startingRef": "main"}]
    assert body["model"] == {"id": "composer-2"}
    assert body["autoCreatePR"] is False
    assert "mcpServers" not in body


@pytest.mark.asyncio
async def test_create_cloud_agent_rejects_response_without_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_request(**_kwargs: Any) -> dict[str, Any]:
        return {}

    client = _client()
    monkeypatch.setattr(client, "_request", _fake_request)

    with pytest.raises(ValueError, match=r"cursor agents\.create response missing agent id"):
        await client.create_cloud_agent(prompt="p", repo_url="u")


@pytest.mark.asyncio
async def test_get_run_and_artifacts_use_the_created_agent_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_request(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        path = kwargs["path"]
        if path == "/v1/agents":
            return {"agent": {"id": "agent-1"}}
        if path.endswith("/artifacts"):
            return {"items": [{"id": "art-1"}, "junk", {"id": "art-2"}]}
        return {"id": "run-1", "status": "completed"}

    client = _client()
    monkeypatch.setattr(client, "_request", _fake_request)

    await client.create_cloud_agent(prompt="p", repo_url="u")
    run = await client.get_run("run-9")
    artifacts = await client.list_artifacts("run-9")

    assert run == {"id": "run-1", "status": "completed"}
    assert artifacts == [{"id": "art-1"}, {"id": "art-2"}]
    assert [call["path"] for call in calls] == [
        "/v1/agents",
        "/v1/agents/agent-1/runs/run-9",
        "/v1/agents/agent-1/artifacts",
    ]


@pytest.mark.asyncio
async def test_get_run_falls_back_to_run_id_before_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_request(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {}

    client = _client()
    monkeypatch.setattr(client, "_request", _fake_request)

    await client.get_run("run-5")

    assert calls[0]["path"] == "/v1/agents/run-5/runs/run-5"


@pytest.mark.asyncio
async def test_list_artifacts_returns_empty_for_non_list_items(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    async def _fake_request(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        return {"items": "nope"}

    client = _client()
    monkeypatch.setattr(client, "_request", _fake_request)

    assert await client.list_artifacts("run-7") == []
    assert calls[0]["path"] == "/v1/agents/run-7/artifacts"


__all__: list[str] = []
