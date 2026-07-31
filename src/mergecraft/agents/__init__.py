"""Agent registry — resolve_agent by id."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.agents.claude import claude
from mergecraft.agents.codex import codex
from mergecraft.agents.gemini import gemini
from mergecraft.agents.opencode import opencode
from mergecraft.agents.shared import Agent, AgentImpl, AgentResult, AgentRunContext, AgentUsage

if TYPE_CHECKING:
    from mergecraft.types import AgentId

agents: dict[str, AgentImpl] = {
    "claude": claude,
    "codex": codex,
    "gemini": gemini,
    "opencode": opencode,
}


def resolve_agent(agent_id: AgentId | str) -> Agent:
    key = str(agent_id).lower().strip()
    found = agents.get(key)
    if found is None:
        available = ", ".join(sorted(agents))
        msg = f"unknown agent {agent_id!r}; available: {available}"
        raise ValueError(msg)
    return found


__all__ = [
    "Agent",
    "AgentResult",
    "AgentRunContext",
    "AgentUsage",
    "agents",
    "claude",
    "codex",
    "gemini",
    "opencode",
    "resolve_agent",
]
