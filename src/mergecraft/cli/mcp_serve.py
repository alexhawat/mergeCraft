"""MCP serve context — resolve workspace, role, and trust tier for external clients (CC4)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mergecraft.config.settings import (
    apply_trust_tier_to_repo_settings,
    load_repo_settings,
    parse_cli_trust_override,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.server import (
    MCP_ENDPOINT,
    MCP_REVIEWER_ENDPOINT,
    MCP_VERIFIER_ENDPOINT,
    build_orchestrator_tools,
    build_reviewer_tools,
    build_verifier_tools,
    create_mcp_app,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.offline_review import resolve_offline_review_trust_tier
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.source_resolve import SourceResolverSpec, resolve_workspace

if TYPE_CHECKING:
    from fastapi import FastAPI

    from mergecraft.mcp.shared import ToolSpec

ServeRole = Literal["orchestrator", "reviewer", "verifier"]


def _role_endpoint(role: ServeRole) -> str:
    if role == "reviewer":
        return MCP_REVIEWER_ENDPOINT
    if role == "verifier":
        return MCP_VERIFIER_ENDPOINT
    return MCP_ENDPOINT


def _parse_role(role: str) -> ServeRole:
    key = role.strip().lower()
    if key not in {"orchestrator", "reviewer", "verifier"}:
        msg = f"unknown role {role!r} (expected orchestrator, reviewer, or verifier)"
        raise ValueError(msg)
    return key  # type: ignore[return-value]  # — key verified against {"orchestrator","reviewer","verifier"} above


def build_mcp_tool_context(
    *,
    cwd: Path,
    invocation_root: Path | None = None,
    trust_override: str | None = None,
) -> ToolContext:
    """Build a :class:`ToolContext` for MCP serve/list with TS1 trust applied."""
    root = cwd.resolve()
    inv_root = (invocation_root or root).resolve()
    spec = SourceResolverSpec(cwd=root, invocation_root=inv_root)
    workspace = resolve_workspace(spec)
    repo_root = workspace.cwd.resolve()
    trust_tier = resolve_offline_review_trust_tier(
        cwd=repo_root,
        invocation_root=inv_root,
        trust_override=parse_cli_trust_override(trust_override),
        cloned=workspace.cloned,
    )
    settings = load_repo_settings(root=repo_root, load_learnings_files=False)
    settings, _drops = apply_trust_tier_to_repo_settings(
        settings,
        trust_tier,
        source_label="CLI mcp serve",
    )
    shell_policy: Literal["disabled", "restricted", "enabled"] = (
        "restricted" if trust_tier == "trusted" else "disabled"
    )
    push_policy: Literal["disabled", "restricted", "enabled"] = (
        "restricted" if trust_tier == "trusted" else "disabled"
    )
    state = init_tool_state(owner="local", name=repo_root.name, dir=str(repo_root))
    state.trust_tier = trust_tier
    modes = compute_modes("claude", signed_commits=False)
    payload = ResolvedPayload(
        event=PayloadEvent(trigger="unknown", title="mcp serve"),
        shell=shell_policy,
        push=push_policy,
        cwd=str(repo_root),
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="local", name=repo_root.name),
        payload=payload,
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=modes,
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(repo_root),
        signed_commits=False,
        pr_approve_enabled=False,
        auto_merge_enabled=False,
        static_checks_enabled=trust_tier == "trusted",
        analyzers_mode="auto",
        trust_tier=trust_tier,  # type: ignore[arg-type]  # — trust_tier is TrustTier; ToolContext.trust_tier field expects str supertype
        analyzers_settings_enabled=settings.analyzers.enabled,
        xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
    )


def resolve_served_tool_specs(
    *,
    cwd: Path,
    role: str,
    invocation_root: Path | None = None,
    trust_override: str | None = None,
) -> list[ToolSpec]:
    """Return the MCP tool surface for a role without starting a server."""
    parsed_role = _parse_role(role)
    ctx = build_mcp_tool_context(
        cwd=cwd,
        invocation_root=invocation_root,
        trust_override=trust_override,
    )
    if parsed_role == "orchestrator":
        return build_orchestrator_tools(ctx)
    if parsed_role == "reviewer":
        return build_reviewer_tools(ctx)
    return build_verifier_tools(ctx)


def resolve_served_tool_names(
    *,
    cwd: Path,
    role: str,
    invocation_root: Path | None = None,
    trust_override: str | None = None,
) -> list[str]:
    return [
        spec.name
        for spec in resolve_served_tool_specs(
            cwd=cwd,
            role=role,
            invocation_root=invocation_root,
            trust_override=trust_override,
        )
    ]


def build_mcp_app_for_role(
    *,
    cwd: Path,
    role: str,
    invocation_root: Path | None = None,
    trust_override: str | None = None,
) -> FastAPI:
    """Stand up an in-process MCP app for tests and tooling."""
    _parse_role(role)
    ctx = build_mcp_tool_context(
        cwd=cwd,
        invocation_root=invocation_root,
        trust_override=trust_override,
    )
    orchestrator_tools = build_orchestrator_tools(ctx)
    role_tools = {
        "reviewer": build_reviewer_tools(ctx),
        "verifier": build_verifier_tools(ctx),
    }
    return create_mcp_app(orchestrator_tools, ctx, role_tools=role_tools)


__all__ = [
    "_role_endpoint",
    "build_mcp_app_for_role",
    "build_mcp_tool_context",
    "resolve_served_tool_names",
    "resolve_served_tool_specs",
]
