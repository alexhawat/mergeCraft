"""``mergecraft agent-local`` — gitignored local roster overrides (wave plan 11 / W4)."""

from __future__ import annotations

from mergecraft.cli.agent_cmd import AgentRosterTarget, create_agent_app

app = create_agent_app(target=AgentRosterTarget.LOCAL)

__all__ = ["app"]
