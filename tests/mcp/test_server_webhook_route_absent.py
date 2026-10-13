"""The per-run MCP app mounts no webhook ingress route.

The removed route authenticated a signed delivery and returned ``200`` without
processing anything. With the surface gone, an unknown ``/webhooks/{provider}``
path must not answer as a route, while the unauthenticated ``/health`` probe and
the Bearer-guarded ``/mcp`` surface keep working.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.server import MCP_ENDPOINT, create_mcp_app
from mergecraft.mcp.shared import ToolClass, ToolResult, ToolSpec

_TOOL_TOKEN = "test-bearer-token"


async def _echo(_arguments: dict[str, Any]) -> ToolResult:
    return ToolResult(content=[{"type": "text", "text": "ok"}])


def _tool_spec() -> ToolSpec:
    return ToolSpec(
        name="echo",
        description="Echo a value back.",
        input_schema={"type": "object", "properties": {}},
        execute=_echo,
        tool_class=ToolClass.ANALYSIS,
    )


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_mcp_app([_tool_spec()], auth_token=_TOOL_TOKEN))


def test_no_webhook_ingress_route_is_mounted(client: TestClient) -> None:
    """A POST to the old ingress path is not a route; ``/health`` still answers."""
    response = client.post("/webhooks/github", content=b'{"ok":true}')
    assert response.status_code in {404, 405}, response.text
    # Surviving surface: the unauthenticated health probe is untouched.
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json().get("status") == "ok"


@pytest.mark.parametrize("provider", ["github", "gitlab", "bitbucket"])
def test_no_provider_specific_webhook_path(client: TestClient, provider: str) -> None:
    """No provider gets an ingress route; the ``/mcp`` surface still serves the tool list."""
    response = client.post(f"/webhooks/{provider}", content=b"{}")
    assert response.status_code in {404, 405}, response.text
    # Surviving surface: /mcp refuses an anonymous caller and serves the bearer.
    assert client.get(MCP_ENDPOINT).status_code == 401
    authorized = client.post(
        MCP_ENDPOINT,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        headers={"Authorization": f"Bearer {_TOOL_TOKEN}"},
    )
    assert authorized.status_code == 200
    assert [entry["name"] for entry in authorized.json()["result"]["tools"]] == ["echo"]
