"""Replay ordered response blocks into mergeCraft agent results."""

from __future__ import annotations

from mergecraft.agents.shared import AgentResult
from mergecraft.mcp.context import ToolContext
from mergecraft.mcp.verdict import record_validated_terminal_submission
from tests.support.provider_harness.schema import ResponseBlock


def replay_blocks(blocks: list[ResponseBlock], *, ctx: ToolContext) -> AgentResult:
    validation_error: str | None = None
    terminal_received = False
    terminal_id: str | None = None
    output_parts: list[str] = []

    for block in blocks:
        if block.kind == "text":
            if block.text:
                output_parts.append(block.text)
            continue
        if block.kind != "tool_call" or block.tool_name != "submit_review_verdict":
            continue
        args = block.arguments or {}
        if "verdict" not in args or "summary" not in args:
            validation_error = "terminal submission rejected: missing required fields"
            break
        try:
            recorded = record_validated_terminal_submission(ctx, args)
            from mergecraft.enterprise.audit import maybe_audit_blocking_terminal_submission

            maybe_audit_blocking_terminal_submission(ctx, recorded)
        except ValueError as exc:
            validation_error = str(exc)
            break
        terminal_received = True
        terminal_id = recorded.id

    return AgentResult(
        success=validation_error is None,
        output="".join(output_parts) if output_parts else None,
        error=validation_error,
        terminal_submission_received=terminal_received,
        terminal_submission_id=terminal_id,
    )
