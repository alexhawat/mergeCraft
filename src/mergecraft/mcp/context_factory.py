"""Minimal :class:`ToolContext` construction for MCP serve and codegen."""

from __future__ import annotations

from typing import Literal

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient


def minimal_tool_context(
    tmpdir: str,
    *,
    repo_owner: str = "local",
    repo_name: str = "mergecraft",
    trust_tier: Literal["trusted", "untrusted"] = "trusted",
    shell: Literal["disabled", "restricted", "enabled"] = "disabled",
    push: Literal["disabled", "restricted", "enabled"] = "disabled",
    payload_cwd: str | None = None,
    payload_title: str | None = None,
    mcp_auth_token: str = "",
    static_checks_enabled: bool = False,
    analyzers_settings_enabled: bool = True,
) -> ToolContext:
    """Build a workspace-scoped :class:`ToolContext` with safe defaults."""
    state = init_tool_state(owner=repo_owner, name=repo_name, dir=tmpdir)
    state.trust_tier = trust_tier
    payload = ResolvedPayload(
        event=PayloadEvent(
            trigger="unknown",
            title=payload_title or ("mcp serve" if payload_cwd else None),
        ),
        shell=shell,
        push=push,
        cwd=payload_cwd,
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner=repo_owner, name=repo_name),
        payload=payload,
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude", signed_commits=False),
        tool_state=state,
        mcp_server_url="",
        mcp_auth_token=mcp_auth_token,
        mcp_orchestrator_auth_token="",
        tmpdir=tmpdir,
        signed_commits=False,
        pr_approve_enabled=False,
        auto_merge_enabled=False,
        static_checks_enabled=static_checks_enabled,
        analyzers_mode="auto",
        trust_tier=trust_tier,
        analyzers_settings_enabled=analyzers_settings_enabled,
        xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
    )


__all__ = ["minimal_tool_context"]
