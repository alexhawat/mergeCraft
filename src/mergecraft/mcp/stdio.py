"""JSON-RPC stdio transport for the public MCP product profile (D7 / D12).

Exports:
    run_public_stdio_server: Serve public ``ToolSpec`` list over stdin/stdout.
"""

from __future__ import annotations

import asyncio
import json
import sys
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.server import (
    RpcError,
    _argument_schema_error,
    _charge_tool_call_budget,
    _coerce_arguments,
    _record_trajectory,
    _rpc_error,
    _span_tool_call_id,
    _tool_result_to_rpc,
)
from mergecraft.mcp.shared import ToolSpec, bind_selected_mode, reset_selected_mode
from mergecraft.tracing._tool_attrs import (
    emit_verb_subevent,
    enrich_tool_request,
    enrich_tool_response,
)
from mergecraft.tracing.tracer import get_tracer_from_settings
from mergecraft.types import MERGECRAFT_MCP_NAME

if TYPE_CHECKING:
    from collections.abc import Mapping

    from jsonschema.protocols import Validator

    from mergecraft.mcp.context import ToolContext


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
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": MERGECRAFT_MCP_NAME, "version": "0.1.0"},
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [tool.list_entry() for tool in tools]},
        }
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return _rpc_error(req_id, RpcError(-32602, "tools/call requires string name"))
        if not isinstance(arguments, dict):
            arguments = {}
        tool = by_name.get(name)
        if tool is None:
            return _rpc_error(req_id, RpcError(-32601, f"Unknown tool: {name}"))
        arguments = _coerce_arguments(arguments, tool.input_schema)
        schema_error = _argument_schema_error(tool, arguments, validators)
        if schema_error is not None:
            _record_trajectory(tool_ctx, name, arguments, ok=False, error=schema_error.message)
            return _rpc_error(req_id, schema_error)
        try:
            from mergecraft.utils.run_bounds import BudgetExhausted

            _charge_tool_call_budget(tool_ctx)
        except BudgetExhausted as exc:
            return _rpc_error(req_id, RpcError(-32000, str(exc)))
        from mergecraft.config.settings import RepoSettings

        tracer = get_tracer_from_settings(RepoSettings())
        call_attrs: dict[str, Any] = {
            "tool.name": name,
            "tool.server": MERGECRAFT_MCP_NAME,
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.id": _span_tool_call_id(),
        }
        with tracer.start_span("tool.call", attrs_source=lambda: dict(call_attrs)) as span:
            enrich_tool_request(span, arguments=arguments)
            mode = tool_ctx.tool_state.selected_mode
            mode_token = bind_selected_mode(mode)
            try:
                result = await tool.execute(arguments)
            except Exception as exc:
                span.set_status("error", str(exc))
                enrich_tool_response(span, output=None, error=exc)
                _record_trajectory(tool_ctx, name, arguments, ok=False, error=str(exc))
                raise
            finally:
                reset_selected_mode(mode_token)
            enrich_tool_response(span, output=result)
            _record_trajectory(tool_ctx, name, arguments, ok=True, result=result)
            emit_verb_subevent(
                tracer,
                parent_span_id=span.span_id,
                tool_name=name,
                attrs=call_attrs,
            )
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": _tool_result_to_rpc(result),
            }
    return _rpc_error(req_id, RpcError(-32601, f"Method not found: {method}"))


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
            _write_response({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}})
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
