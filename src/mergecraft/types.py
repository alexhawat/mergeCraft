"""Shared types and MCP tool-name helpers (ported from mergecraft external.ts)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ── agent / MCP ───────────────────────────────────────────────────────────────

AgentId = Literal["claude", "opencode"]

MERGECRAFT_MCP_NAME = "mergecraft"
# Back-compat alias matching the TS export name style in prompts/docs.
# Subagent name used in mode prompts (agents/reviewer.ts).
REVIEWER_AGENT_NAME = "mergecraft-reviewer"


def format_mcp_tool_ref(agent_id: AgentId, tool_name: str) -> str:
    """Format a tool name the way each agent's MCP client presents it to the model.

    claude code: mcp__mergecraft__select_mode
    opencode:    mergecraft_select_mode
    """
    match agent_id:
        case "claude":
            return f"mcp__{MERGECRAFT_MCP_NAME}__{tool_name}"
        case "opencode":
            return f"{MERGECRAFT_MCP_NAME}_{tool_name}"
        case _:
            raise ValueError(f"unknown agent id: {agent_id!r}")


# ── tool / runtime permissions ────────────────────────────────────────────────

ToolPermission = Literal["disabled", "enabled"]
ShellPermission = Literal["disabled", "restricted", "enabled"]
PushPermission = Literal["disabled", "restricted", "enabled"]
StatusChecksPermission = Literal["disabled", "enabled"]

# ── workflow.yml GITHUB_TOKEN permissions ─────────────────────────────────────

WorkflowPermissionValue = Literal["read", "write", "none"]
WorkflowIdTokenPermissionValue = Literal["write", "none"]


class WorkflowPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    actions: WorkflowPermissionValue | None = None
    attestations: WorkflowPermissionValue | None = None
    checks: WorkflowPermissionValue | None = None
    contents: WorkflowPermissionValue | None = None
    deployments: WorkflowPermissionValue | None = None
    discussions: WorkflowPermissionValue | None = None
    id_token: WorkflowIdTokenPermissionValue | None = Field(default=None, alias="id-token")
    issues: WorkflowPermissionValue | None = None
    models: WorkflowPermissionValue | None = None
    packages: WorkflowPermissionValue | None = None
    pages: WorkflowPermissionValue | None = None
    pull_requests: WorkflowPermissionValue | None = Field(default=None, alias="pull-requests")
    repository_projects: WorkflowPermissionValue | None = Field(
        default=None, alias="repository-projects"
    )
    security_events: WorkflowPermissionValue | None = Field(default=None, alias="security-events")
    statuses: WorkflowPermissionValue | None = None


# GitHub permission levels: admin > write > maintain > triage > read > none
AuthorPermission = Literal["admin", "maintain", "write", "triage", "read", "none"]


class XrepoConfig(BaseModel):
    """Cross-repo intent + resolved access sets (server-side)."""

    model_config = ConfigDict(extra="forbid")

    mode: Literal["all", "explicit"]
    read: list[str]
    write: list[str]
    unavailable: list[str] | None = None
