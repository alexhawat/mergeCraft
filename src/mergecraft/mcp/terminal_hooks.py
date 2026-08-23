"""Orchestration-boundary hooks after terminal verdict recording."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.tool_state import TerminalSubmission


def after_terminal_submission_recorded(
    ctx: ToolContext,
    recorded: TerminalSubmission,
) -> None:
    """Run post-record side effects (enterprise audit, etc.) outside verdict core."""
    from mergecraft.enterprise.audit import maybe_audit_blocking_terminal_submission

    maybe_audit_blocking_terminal_submission(ctx, recorded)
