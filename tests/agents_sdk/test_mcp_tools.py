"""In-process public MCP tool wiring tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.agents_sdk.mcp_tools import call_public_tool, tool_context_for_workspace


@pytest.mark.asyncio
async def test_get_capabilities_tool_wires_public_mcp(tmp_path: Path) -> None:
    ctx = tool_context_for_workspace(tmp_path)
    payload = await call_public_tool(ctx, "get_capabilities")
    assert "error" not in payload
    assert "capabilities" in payload or "allowed" in payload
