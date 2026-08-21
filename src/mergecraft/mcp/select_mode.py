"""select_mode tool."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.modes import is_write_capable_mode_name
from mergecraft.types import format_mcp_tool_ref

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


def select_mode_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]):
        if ctx.tool_state.selected_mode:
            return {
                "error": (
                    f'mode already selected: "{ctx.tool_state.selected_mode}". '
                    "mode selection is final and cannot be changed."
                )
            }
        mode_name = str(params["mode"])
        selectable = [m for m in ctx.modes if not is_write_capable_mode_name(m.name)]
        selected = next(
            (m for m in selectable if m.name.lower() == mode_name.lower()),
            None,
        )
        if selected is None:
            return {
                "error": f'mode "{mode_name}" not found',
                "availableModes": [
                    {"name": m.name, "description": m.description} for m in selectable
                ],
            }
        ctx.tool_state.selected_mode = selected.name
        parent = {"IncrementalReview": "Review", "Fix": "Build"}.get(selected.name, selected.name)
        user_instructions = ctx.mode_instructions.get(parent, "")
        guidance = "\n\n".join(p for p in (selected.prompt, user_instructions) if p)
        result: dict[str, Any] = {
            "modeName": selected.name,
            "description": selected.description,
            "orchestratorGuidance": guidance
            or f"Follow the {selected.name} mode workflow. Use "
            f"`{format_mcp_tool_ref(ctx.agent_id, 'report_progress')}` for updates.",
        }
        if (
            selected.name == "Plan"
            and (params.get("issue_number") or ctx.payload.event.issue_number)
            and ctx.tool_state.existing_plan_comment_id
        ):
            result["previousPlanBody"] = ctx.tool_state.previous_plan_body
        if selected.name in {"Review", "IncrementalReview"} and ctx.tool_state.summary_file_path:
            result["summaryFilePath"] = ctx.tool_state.summary_file_path
        return result

    return tool(
        name="select_mode",
        tool_class=ToolClass.SCOPE,
        mutates=True,
        description=("Select a mode and receive step-by-step guidance on how to handle the task."),
        input_schema={
            "type": "object",
            "properties": {
                "mode": {"type": "string"},
                "issue_number": {"type": "number"},
            },
            "required": ["mode"],
            "additionalProperties": False,
        },
        execute=execute(_run, "select_mode"),
    )
