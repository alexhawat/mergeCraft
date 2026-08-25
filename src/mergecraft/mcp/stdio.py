"""JSON-RPC stdio transport for the public MCP product profile (D7 / D12).

Exports:
    run_public_stdio_server: Serve public ``ToolSpec`` list over stdin/stdout.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.rpc import dispatch_mcp_rpc
from mergecraft.mcp.rpc_types import json_rpc_parse_error

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jsonschema.protocols import Validator

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec


def _write_response(response: Mapping[str, Any]) -> None:
    sys.stdout.write(json.dumps(response) + "\n")
    sys.stdout.flush()


async def _handle_rpc(
    body: dict[str, Any],
    *,
    tools: list[ToolSpec],
    by_name: dict[str, ToolSpec],
    tool_ctx: ToolContext,
    validators: dict[str, Validator],
) -> dict[str, Any] | None:
    """Dispatch one JSON-RPC request; return ``None`` for notifications."""
    if "id" not in body:
        return None
    req_id = body.get("id")
    method = body.get("method")
    params = body.get("params") or {}
    if not isinstance(params, dict):
        params = {}
    return await dispatch_mcp_rpc(
        req_id,
        method,
        params,
        tools=tools,
        by_name=by_name,
        tool_ctx=tool_ctx,
        validators=validators,
        return_tool_errors=True,
    )


async def _serve_stdio_loop(tools: list[ToolSpec], tool_ctx: ToolContext) -> None:
    by_name = {tool.name: tool for tool in tools}
    validators: dict[str, Validator] = {}
    while True:
        line = await asyncio.to_thread(sys.stdin.readline)
        if not line:
            break
        stripped = line.strip()
        if not stripped:
            continue
        try:
            body = json.loads(stripped)
        except json.JSONDecodeError:
            _write_response(json_rpc_parse_error(include_id=True, req_id=None))
            continue
        if isinstance(body, list):
            for item in body:
                if not isinstance(item, dict):
                    continue
                response = await _handle_rpc(
                    item,
                    tools=tools,
                    by_name=by_name,
                    tool_ctx=tool_ctx,
                    validators=validators,
                )
                if response is not None:
                    _write_response(response)
            continue
        if not isinstance(body, dict):
            continue
        response = await _handle_rpc(
            body,
            tools=tools,
            by_name=by_name,
            tool_ctx=tool_ctx,
            validators=validators,
        )
        if response is not None:
            _write_response(response)


def run_public_stdio_server(tool_ctx: ToolContext, tools: list[ToolSpec]) -> None:
    """Run the public MCP profile over newline-delimited JSON-RPC on stdio."""
    asyncio.run(_serve_stdio_loop(tools, tool_ctx))


__all__ = ["run_public_stdio_server"]
