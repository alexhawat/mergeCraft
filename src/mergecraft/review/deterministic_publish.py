"""Deterministic review publication when the agent cannot finish (plan 12 seam).

Plan 12 W5 owns the full implementation; plan 13 W5 calls this entry point
when scope or policy rejection makes a post-run resume pointless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mergecraft.agents.shared import AgentRunContext


def publish_scope_unavailable_review(
    ctx: AgentRunContext,
    *,
    verdict_diagnostic: str,
    **kwargs: Any,
) -> None:
    """Record a scope-unavailable review without resuming the agent.

    Stub until plan 12 W5 Step 4 lands the owned publication path.
    """
    _ = ctx, verdict_diagnostic, kwargs
