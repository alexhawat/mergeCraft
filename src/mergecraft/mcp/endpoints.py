"""MCP endpoint path constants and the role-URL helper shared by all agent drivers.

Agents import from this module (not from ``mcp.server``) to avoid pulling
the FastAPI / uvicorn dependency stack into agent driver imports.
``mcp.server`` re-exports the path constants for backward-compatible access.
"""

from __future__ import annotations

from mergecraft.types import VERIFIER_AGENT_NAME

MCP_ENDPOINT: str = "/mcp"
MCP_REVIEWER_ENDPOINT: str = "/mcp/reviewer"
MCP_VERIFIER_ENDPOINT: str = "/mcp/verifier"


def mcp_role_url(base: str, agent_id: str | None) -> str:
    """Derive the role-specific MCP URL from the base URL and the current agent id.

    Strips any existing role suffix first so this is idempotent when the
    caller already holds a role URL.

    Role map (D14):
    - verifier → ``/mcp/verifier``
    - reviewer / judge / classifier / anything else → ``/mcp/reviewer``
    """
    for suffix in (MCP_REVIEWER_ENDPOINT, MCP_VERIFIER_ENDPOINT, MCP_ENDPOINT):
        if base.endswith(suffix):
            host = base[: -len(suffix)]
            break
    else:
        host = base
    if agent_id == VERIFIER_AGENT_NAME:
        return host + MCP_VERIFIER_ENDPOINT
    return host + MCP_REVIEWER_ENDPOINT
