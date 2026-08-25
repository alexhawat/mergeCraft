"""Shared MCP tool-call helpers — argument coercion, validation, trajectory, RPC shaping."""

from __future__ import annotations

import json
from math import isfinite
from typing import TYPE_CHECKING, Any

from jsonschema import SchemaError
from jsonschema.exceptions import best_match
from jsonschema.validators import validator_for
from loguru import logger

from mergecraft.mcp.rpc import RpcError
from mergecraft.mcp.shared import JsonSchema, ToolResult, ToolSpec

if TYPE_CHECKING:
    from jsonschema.protocols import Validator

    from mergecraft.mcp.context import ToolContext


def tool_result_to_rpc(result: ToolResult | Any) -> dict[str, Any]:
    if isinstance(result, ToolResult):
        out: dict[str, Any] = {"content": result.content}
        if result.is_error:
            out["isError"] = True
        return out
    if isinstance(result, dict) and "content" in result:
        return result
    return {"content": [{"type": "text", "text": json.dumps(result, default=str)}]}


def span_tool_call_id() -> str:
    """Generate a stable id for a ``tool.call`` span's ``gen_ai.tool.call.id``."""
    import uuid

    return uuid.uuid4().hex


def charge_tool_call_budget(ctx: ToolContext | None) -> None:
    """Increment the per-run tool-call budget before executing an MCP tool."""
    if ctx is None or ctx.budget_tracker is None:
        return
    ctx.budget_tracker.record_tool_call()


def record_trajectory(
    ctx: ToolContext | None,
    name: str,
    arguments: dict[str, Any],
    *,
    ok: bool,
    result: Any = None,
    error: str | None = None,
) -> None:
    """Record one mediated tool call on the run's trajectory (#43, D8)."""
    if ctx is None:
        return
    try:
        from mergecraft.evidence.trajectory import outcome_ok_from_result, record_tool_call

        record_tool_call(
            ctx.tool_state,
            tool=name,
            arguments=arguments,
            ok=ok,
            outcome_ok=outcome_ok_from_result(result) if ok else None,
            error=error,
        )
    except Exception as exc:  # an audit trail never breaks a tool call
        logger.debug("trajectory: failed to record {} — {}", name, exc)


_TRUE_STRINGS = frozenset({"true", "1"})
_FALSE_STRINGS = frozenset({"false", "0"})


def _declared_types(schema: JsonSchema | None) -> frozenset[str]:
    """Return the ``type`` keywords a property schema declares."""
    declared = schema.get("type") if schema is not None else None
    if isinstance(declared, str):
        return frozenset({declared})
    if isinstance(declared, list):
        return frozenset(item for item in declared if isinstance(item, str))
    return frozenset()


def _coerce_scalar(value: object, types: frozenset[str]) -> object:
    """Read a string-encoded scalar as the type the schema declares, or leave it."""
    if not isinstance(value, str) or "string" in types:
        return value
    text = value.strip()
    if "integer" in types:
        try:
            return int(text)
        except ValueError:
            return value
    if "number" in types:
        try:
            number = int(text) if text.lstrip("+-").isdigit() else float(text)
        except ValueError:
            return value
        if isinstance(number, float) and not isfinite(number):
            return value
        return number
    if "boolean" in types:
        folded = text.casefold()
        if folded in _TRUE_STRINGS:
            return True
        if folded in _FALSE_STRINGS:
            return False
    return value


def coerce_arguments(arguments: dict[str, Any], schema: JsonSchema) -> dict[str, Any]:
    """Absorb loosely-typed scalars models routinely send at the MCP boundary."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return arguments
    coerced = dict(arguments)
    for key, value in arguments.items():
        declared = properties.get(key)
        types = _declared_types(declared if isinstance(declared, dict) else None)
        if types:
            coerced[key] = _coerce_scalar(value, types)
    return coerced


def argument_schema_error(
    tool: ToolSpec,
    arguments: dict[str, Any],
    cache: dict[str, Validator],
) -> RpcError | None:
    """Check ``arguments`` against ``tool.input_schema``; return an error or ``None``."""
    validator = cache.get(tool.name)
    if validator is None:
        validator_cls = validator_for(tool.input_schema)
        try:
            validator_cls.check_schema(tool.input_schema)
        except SchemaError as exc:
            return RpcError(
                -32603, f"tool {tool.name} declares an invalid input schema: {exc.message}"
            )
        validator = validator_cls(tool.input_schema)
        cache[tool.name] = validator
    error = best_match(validator.iter_errors(arguments))
    if error is None:
        return None
    return RpcError(
        -32602, f"invalid arguments for {tool.name} at {error.json_path}: {error.message}"
    )


__all__ = [
    "argument_schema_error",
    "charge_tool_call_budget",
    "coerce_arguments",
    "record_trajectory",
    "span_tool_call_id",
    "tool_result_to_rpc",
]
