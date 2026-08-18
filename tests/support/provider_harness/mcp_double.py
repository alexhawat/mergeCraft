"""Scripted MCP test double built on ``create_mcp_app``."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from starlette.testclient import TestClient

from mergecraft.mcp.server import create_mcp_app


@dataclass
class ScriptedMcpClient:
    client: TestClient
    script: dict[str, Any] = field(default_factory=dict)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        calls: dict[str, Any] = self.script.get("calls", {})
        if tool_name not in calls:
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {"name": tool_name, "arguments": arguments},
            }
            return self.client.post("/", json=payload).json()
        entry = calls[tool_name]
        if entry.get("error"):
            return {"error": entry["error"]}
        return {"result": entry.get("result", {})}


def scripted_mcp_app(script: dict[str, Any]) -> ScriptedMcpClient:
    return ScriptedMcpClient(client=TestClient(create_mcp_app([])), script=script)
