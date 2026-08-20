"""Streamable-HTTP transport conformance for the mergeCraft MCP endpoint."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec


async def _echo(_arguments: dict[str, Any]) -> ToolResult:
    return ToolResult(content=[{"type": "text", "text": "ok"}])


@pytest.fixture
def client() -> TestClient:
    spec = ToolSpec(
        name="echo",
        description="Echo a value back.",
        input_schema={"type": "object", "properties": {}},
        execute=_echo,
        tool_class=ToolClass.ANALYSIS,
    )
    return TestClient(create_mcp_app([spec]))


def test_initialize_returns_a_response(client: TestClient) -> None:
    response = client.post(
        MCP_ENDPOINT,
        json={"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 0
    assert body["result"]["serverInfo"]["name"]


def test_initialized_notification_gets_202_with_no_body(client: TestClient) -> None:
    """A notification carries no ``id``, so it must not be answered with a response.

    Codex's rmcp client kills its transport worker when it cannot deserialize the
    reply, which leaves the server permanently "not ready" for the whole session.
    """
    response = client.post(
        MCP_ENDPOINT,
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
    )
    assert response.status_code == 202
    assert response.content == b""


def test_notification_only_batch_gets_202(client: TestClient) -> None:
    response = client.post(
        MCP_ENDPOINT,
        json=[
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "method": "notifications/cancelled"},
        ],
    )
    assert response.status_code == 202
    assert response.content == b""


def test_batch_containing_a_request_still_gets_responses(client: TestClient) -> None:
    response = client.post(
        MCP_ENDPOINT,
        json=[
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        ],
    )
    assert response.status_code == 200
    # Notifications carry no ``id`` and must not produce a response; only the
    # request (id=1) is dispatched to handle_rpc.
    assert [entry.get("id") for entry in response.json()] == [1]


def test_notification_shaped_tools_call_in_mixed_batch_is_not_executed(
    client: TestClient,
) -> None:
    """A tools/call without ``id`` (notification-shaped) in a mixed batch must not execute.

    JSON-RPC notifications must not receive a response. A notification-shaped
    ``tools/call`` must be silently dropped from the batch — never dispatched to
    ``handle_rpc``, never executed. Only the requests (those with an ``id``) get
    responses.
    """
    response = client.post(
        MCP_ENDPOINT,
        json=[
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            # notification-shaped tools/call (no ``id``) — must be skipped entirely
            {
                "jsonrpc": "2.0",
                "method": "tools/call",
                "params": {"name": "echo", "arguments": {}},
            },
        ],
    )
    assert response.status_code == 200
    body = response.json()
    # Only the initialize response; the notification-shaped tools/call produces no entry.
    assert isinstance(body, list)
    assert len(body) == 1, f"notification-shaped tools/call must not produce a response: {body}"
    assert body[0]["id"] == 1


def test_tools_list_after_handshake(client: TestClient) -> None:
    client.post(MCP_ENDPOINT, json={"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    client.post(MCP_ENDPOINT, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
    response = client.post(MCP_ENDPOINT, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [entry["name"] for entry in response.json()["result"]["tools"]] == ["echo"]
