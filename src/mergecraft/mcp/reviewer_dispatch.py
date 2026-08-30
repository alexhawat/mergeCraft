"""Record multi-reviewer roster dispatch failures on ``ToolState`` (D15)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from mergecraft.mcp.shared import ToolClass, execute, tool
from mergecraft.mcp.tool_state import record_reviewer_dispatch_error

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


class RecordReviewerDispatchErrorParams(BaseModel):
    """Parameters for ``record_reviewer_dispatch_error``."""

    agent_id: str = Field(
        min_length=1, description="Reviewer agent id that failed to produce findings."
    )
    reason: str = Field(
        min_length=1, description="Why the reviewer produced no findings (quota, timeout, …)."
    )


def record_reviewer_dispatch_error_tool(ctx: ToolContext):
    async def _run(params: dict[str, Any]) -> dict[str, Any]:
        validated = RecordReviewerDispatchErrorParams.model_validate(params)
        record_reviewer_dispatch_error(
            ctx.tool_state,
            agent_id=validated.agent_id,
            reason=validated.reason,
        )
        return {
            "recorded": True,
            "agent_id": validated.agent_id,
            "reason": validated.reason,
        }

    return tool(
        name="record_reviewer_dispatch_error",
        description=(
            "Record that a roster reviewer subagent failed or produced no findings. "
            "Call once per failed reviewer before submit_review_verdict so the "
            "terminal summary names which reviewers degraded and why (D15)."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Reviewer binding id (for example reviewer2).",
                },
                "reason": {
                    "type": "string",
                    "description": "Failure reason shown in the degradation summary.",
                },
            },
            "required": ["agent_id", "reason"],
            "additionalProperties": False,
        },
        tool_class=ToolClass.REVIEW_WRITE,
        mutates=True,
        execute=execute(_run, "record_reviewer_dispatch_error"),
    )


__all__ = [
    "RecordReviewerDispatchErrorParams",
    "record_reviewer_dispatch_error_tool",
]
