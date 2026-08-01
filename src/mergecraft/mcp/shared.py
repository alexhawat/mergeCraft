"""MCP tool primitives: ToolSpec, mutates flag, tool() helper."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

JsonSchema = dict[str, Any]
# Tool bodies vary across modules; wrap loosely then normalize in ``execute``.
ToolBody = Callable[..., Awaitable[Any]]
ToolHandler = Callable[[Mapping[str, Any]], Awaitable[Any]]


@dataclass(slots=True)
class ToolResult:
    content: list[dict[str, str]]
    is_error: bool = False


@dataclass(slots=True)
class ToolSpec:
    """A mergeCraft MCP tool definition.

    ``mutates`` marks a named state-changing tool that must be reserved for the
    orchestrator and denied to subagents.
    """

    name: str
    description: str
    input_schema: JsonSchema
    execute: ToolHandler
    mutates: bool = False
    annotations: dict[str, Any] = field(default_factory=dict)
    timeout_ms: int | None = None

    def list_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.annotations:
            entry["annotations"] = self.annotations
        return entry


def tool(
    *,
    name: str,
    description: str,
    input_schema: JsonSchema,
    execute: ToolHandler,
    mutates: bool = False,
    annotations: dict[str, Any] | None = None,
    timeout_ms: int | None = None,
) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        input_schema=input_schema,
        execute=execute,
        mutates=mutates,
        annotations=annotations or {},
        timeout_ms=timeout_ms,
    )


def handle_tool_success(data: Mapping[str, Any] | str) -> ToolResult:
    text = data if isinstance(data, str) else json.dumps(data, indent=2, default=str)
    return ToolResult(content=[{"type": "text", "text": text}])


def handle_tool_error(error: object) -> ToolResult:
    message = str(error)
    if isinstance(error, Exception):
        message = str(error)
    return ToolResult(content=[{"type": "text", "text": f"Error: {message}"}], is_error=True)


def get_http_status(err: object) -> int | None:
    status = getattr(err, "status", None)
    if isinstance(status, int):
        return status
    response = getattr(err, "response", None)
    code = getattr(response, "status_code", None)
    return code if isinstance(code, int) else None


def execute(fn: ToolBody, tool_name: str | None = None) -> ToolHandler:
    """Wrap a tool body with success/error ToolResult handling."""

    async def _fn(params: Mapping[str, Any]) -> ToolResult:
        try:
            result = await fn(params)
            if isinstance(result, Mapping | str):
                return handle_tool_success(result)
            return handle_tool_success({"result": result})
        except Exception as error:
            prefix = f"[{tool_name}]" if tool_name else "tool"
            logger.info("{} error: {}", prefix, error)
            logger.debug("{} params: {}", prefix, params)
            return handle_tool_error(error)

    return _fn


EMPTY_SCHEMA: JsonSchema = {"type": "object", "properties": {}, "additionalProperties": False}
