"""Shared JSON-RPC dispatch for HTTP and stdio MCP transports.

Exports:
    RpcError: JSON-RPC error code/message pair.
    rpc_error: Wrap an ``RpcError`` in a response envelope.
    dispatch_mcp_rpc: Handle ``initialize``, ``tools/list``, and ``tools/call``.
    mcp_server_version: Installed package version for ``serverInfo``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, NamedTuple

from mergecraft.mcp.shared import bind_selected_mode, reset_selected_mode
from mergecraft.tracing._tool_attrs import (
    emit_verb_subevent,
    enrich_tool_request,
    enrich_tool_response,
)
from mergecraft.tracing.tracer import get_tracer_from_settings
from mergecraft.types import MERGECRAFT_MCP_NAME

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolSpec


class RpcError(NamedTuple):
    """A JSON-RPC error code/message pair, before it is wrapped in an envelope."""

    code: int
    message: str


def rpc_error(req_id: Any, error: RpcError) -> dict[str, Any]:
    """Wrap ``error`` in the JSON-RPC response envelope for ``req_id``."""
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": error.code, "message": error.message},
    }


def package_version() -> str:
    """Return mergeCraft version from ``pyproject.toml`` (MCP metadata canonical source)."""
    import tomllib
    from pathlib import Path

    root = Path(__file__).resolve().parents[3]
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    version = data.get("project", {}).get("version")
    if isinstance(version, str) and version.strip():
        return version
    from mergecraft import __version__

    return __version__


def mcp_server_version() -> str:
    """Return the mergeCraft version for MCP ``serverInfo``."""
    return package_version()


async def dispatch_mcp_rpc(
    req_id: Any,
    method: str | None,
    params: dict[str, Any],
    *,
    tools: list[ToolSpec],
    by_name: dict[str, ToolSpec],
    tool_ctx: ToolContext | None,
    validators: dict[str, Validator],
    agent_id: str | None = None,
    return_tool_errors: bool = False,
) -> dict[str, Any]:
    """Dispatch one JSON-RPC MCP request and return a response envelope."""
    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": MERGECRAFT_MCP_NAME,
                    "version": mcp_server_version(),
                },
            },
        }
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": [tool.list_entry() for tool in tools]},
        }
    if method == "tools/call":
        from mergecraft.mcp.server import (
            _argument_schema_error,
            _charge_tool_call_budget,
            _coerce_arguments,
            _record_trajectory,
            _span_tool_call_id,
            _tool_result_to_rpc,
        )

        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(name, str):
            return rpc_error(req_id, RpcError(-32602, "tools/call requires string name"))
        if not isinstance(arguments, dict):
            arguments = {}
        tool = by_name.get(name)
        if tool is None:
            return rpc_error(req_id, RpcError(-32601, f"Unknown tool: {name}"))
        arguments = _coerce_arguments(arguments, tool.input_schema)
        schema_error = _argument_schema_error(tool, arguments, validators)
        if schema_error is not None:
            _record_trajectory(tool_ctx, name, arguments, ok=False, error=schema_error.message)
            return rpc_error(req_id, schema_error)
        try:
            from mergecraft.utils.run_bounds import BudgetExhausted

            _charge_tool_call_budget(tool_ctx)
        except BudgetExhausted as exc:
            return rpc_error(req_id, RpcError(-32000, str(exc)))
        from mergecraft.config.settings import RepoSettings

        tracer = get_tracer_from_settings(RepoSettings())
        call_attrs: dict[str, Any] = {
            "tool.name": name,
            "tool.server": MERGECRAFT_MCP_NAME,
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": name,
            "gen_ai.tool.call.id": _span_tool_call_id(),
        }
        if agent_id:
            call_attrs["mergecraft.agent.id"] = agent_id
        with tracer.start_span("tool.call", attrs_source=lambda: dict(call_attrs)) as span:
            enrich_tool_request(span, arguments=arguments)
            mode = tool_ctx.tool_state.selected_mode if tool_ctx is not None else None
            mode_token = bind_selected_mode(mode)
            try:
                result = await tool.execute(arguments)
            except Exception as exc:
                span.set_status("error", str(exc))
                enrich_tool_response(span, output=None, error=exc)
                _record_trajectory(tool_ctx, name, arguments, ok=False, error=str(exc))
                if return_tool_errors:
                    return rpc_error(req_id, RpcError(-32603, str(exc)))
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
    return rpc_error(req_id, RpcError(-32601, f"Method not found: {method}"))


__all__ = [
    "RpcError",
    "dispatch_mcp_rpc",
    "mcp_server_version",
    "package_version",
    "rpc_error",
]
