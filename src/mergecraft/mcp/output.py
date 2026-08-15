"""set_output tool."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import JsonSchema, ToolClass, execute, tool

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def set_output_tool(ctx: ToolContext, output_schema: JsonSchema | None = None):
    if output_schema is not None:

        async def _run_schema(params: dict[str, Any]):
            ctx.tool_state.output = json.dumps(params)
            return {"success": True}

        return tool(
            name="set_output",
            tool_class=ToolClass.ANALYSIS,
            mutates=True,
            description=(
                "Set the structured action output. You MUST call this tool before "
                "finishing — the output is required."
            ),
            input_schema=output_schema,
            execute=execute(_run_schema, "set_output"),
        )

    async def _run(params: dict[str, Any]):
        ctx.tool_state.output = str(params["value"])
        return {"success": True}

    return tool(
        name="set_output",
        tool_class=ToolClass.ANALYSIS,
        mutates=True,
        description=(
            "Set the action output. Exposes the value as the 'result' GitHub Action "
            "output for downstream workflow steps."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "value": {
                    "type": "string",
                    "description": "the output value to expose as a GitHub Action output",
                }
            },
            "required": ["value"],
            "additionalProperties": False,
        },
        execute=execute(_run, "set_output"),
    )
