"""Shared preparation of trusted settings and static checks."""

from __future__ import annotations

from typing import TYPE_CHECKING

from loguru import logger

from mergecraft.agents.activity_watchdog import DEFAULT_IDLE_TIMEOUT_S
from mergecraft.agents.shared import AgentRunContext
from mergecraft.review_checks import StaticCheckConfig

if TYPE_CHECKING:
    from collections.abc import Sequence

    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext


def bind_filtered_execution_settings(
    settings: RepoSettings,
    trust_tier: str,
    drops: dict[str, str],
) -> str:
    """Bind enterprise controls after filtering executable settings.

    Args:
        settings: Run-start repository settings filtered by execution trust.
        trust_tier: Execution trust derived by the entry point.
        drops: Diagnostic reasons from the execution trust filter.

    Returns:
        The skip reason to include in agent instructions.
    """
    from mergecraft.config.settings import build_executable_config_skip_reason
    from mergecraft.enterprise.runtime import bind_enterprise_after_trust

    bind_enterprise_after_trust(settings, trust_tier)
    for reason in drops.values():
        logger.warning("» {}", reason)
    return build_executable_config_skip_reason(drops) if drops else ""


def configured_static_checks(settings: RepoSettings) -> list[StaticCheckConfig]:
    """Convert the run's configured static checks to tool context rows."""
    return [
        StaticCheckConfig(
            name=check.name,
            command=check.command,
            suffixes=tuple(check.suffixes),
        )
        for check in settings.static_checks
    ]


def build_reviewer_context(
    tool_context: ToolContext,
    *,
    payload: object,
    mcp_server_url: str,
    instructions: object,
    subagent_denied_tools: Sequence[str],
    verifier_denied_tools: Sequence[str] = (),
    idle_timeout_s: float = DEFAULT_IDLE_TIMEOUT_S,
) -> AgentRunContext:
    """Bind the reviewer to the admitted MCP run and rendered instructions.

    Args:
        tool_context: Tool state, authorization, and model for the active run.
        payload: Entry point payload to pass to the harness.
        mcp_server_url: Role-specific MCP endpoint.
        instructions: Instructions rendered for the selected harness.
        subagent_denied_tools: Tools withheld from subagents.
        verifier_denied_tools: Tools withheld from verifiers.
        idle_timeout_s: Watchdog deadline for a quiet reviewer.

    Returns:
        The run context passed to the selected reviewer.
    """
    return AgentRunContext(
        payload=payload,
        mcp_server_url=mcp_server_url,
        mcp_auth_token=tool_context.mcp_auth_token,
        tmpdir=tool_context.tmpdir,
        subagent_denied_tools=subagent_denied_tools,
        verifier_denied_tools=verifier_denied_tools,
        instructions=instructions,
        tool_state=tool_context.tool_state,
        api_token=tool_context.api_token,
        resolved_model=tool_context.resolved_model,
        idle_timeout_s=idle_timeout_s,
    )
