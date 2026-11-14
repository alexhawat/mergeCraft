"""Model dispatch and provider budget shared by review entry points."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mergecraft.utils.agent_resolve import run_with_model_chain

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from mergecraft.agents.shared import AgentResult
    from mergecraft.config.settings import RepoSettings
    from mergecraft.jev.cost import TokenBudget
    from mergecraft.mcp.tool_state import ToolState


def resolve_review_provider_budget(*, model: str, max_tokens: int) -> TokenBudget:
    """Use the current review budget or start an advisory provider budget."""
    from mergecraft.agents.token_budget import current_run_budget, token_budget_for

    return current_run_budget() or token_budget_for(
        model=model,
        max_tokens=max_tokens,
        advisory=True,
    )


@dataclass(frozen=True, slots=True)
class ReviewerDispatchResult:
    """The reviewer result and its winning model slug."""

    winning_slug: str | None
    agent_result: AgentResult


async def dispatch_reviewer(
    settings: RepoSettings,
    *,
    model_head: str | None,
    model_pin: bool,
    tool_state: ToolState,
    run_once: Callable[[str], Awaitable[AgentResult]],
    single_attempt: Callable[[], Awaitable[tuple[str | None, AgentResult]]] | None = None,
) -> ReviewerDispatchResult:
    """Dispatch the configured model chain or an explicitly selected single attempt.

    Args:
        settings: Resolved settings for the reviewer and fallback chain.
        model_head: Model requested at the head of the chain.
        model_pin: Whether to collapse the chain to one model.
        tool_state: Shared evidence and terminal submission state.
        run_once: How this entry point runs one fallback candidate.
        single_attempt: Standalone attempt when the entry point bypasses the chain.

    Returns:
        The attempt result and its selected or winning model slug.
    """
    if single_attempt is not None:
        winning_slug, agent_result = await single_attempt()
        return ReviewerDispatchResult(winning_slug, agent_result)
    winning_slug, agent_result = await run_with_model_chain(
        settings=settings,
        run_once=run_once,
        head=model_head,
        pin=model_pin,
        tool_state=tool_state,
    )
    return ReviewerDispatchResult(winning_slug, agent_result)
