"""Agent registry — resolve_agent by id."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from typing import TYPE_CHECKING

from mergecraft.agents.shared import Agent, AgentImpl, AgentResult, AgentRunContext, AgentUsage

if TYPE_CHECKING:
    from mergecraft.types import AgentId

_agents: dict[str, AgentImpl] | None = None


def _agent_table() -> dict[str, AgentImpl]:
    global _agents
    if _agents is None:
        from mergecraft.agents.claude import claude
        from mergecraft.agents.codex import codex
        from mergecraft.agents.cursor import cursor
        from mergecraft.agents.gemini import gemini
        from mergecraft.agents.opencode import opencode

        _agents = {
            "claude": claude,
            "codex": codex,
            "cursor": cursor,
            "gemini": gemini,
            "opencode": opencode,
        }
    return _agents


class _AgentsTable(Mapping[str, AgentImpl]):
    def __getitem__(self, key: str) -> AgentImpl:
        return _agent_table()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(_agent_table())

    def __len__(self) -> int:
        return len(_agent_table())


agents: dict[str, AgentImpl] = _AgentsTable()  # type: ignore[assignment]


def resolve_agent(agent_id: AgentId | str) -> Agent:
    key = str(agent_id).lower().strip()
    found = _agent_table().get(key)
    if found is None:
        available = ", ".join(sorted(_agent_table()))
        msg = f"unknown agent {agent_id!r}; available: {available}"
        raise ValueError(msg)
    return found


def __getattr__(name: str) -> AgentImpl:
    table = _agent_table()
    if name in table:
        return table[name]
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "Agent",
    "AgentResult",
    "AgentRunContext",
    "AgentUsage",
    "agents",
    "claude",
    "codex",
    "cursor",
    "gemini",
    "opencode",
    "resolve_agent",
]
