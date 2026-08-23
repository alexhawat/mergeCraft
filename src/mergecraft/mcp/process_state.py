"""Process-wide MCP state that must not leak across tests under xdist (#421 / D4)."""

from __future__ import annotations

from mergecraft.mcp.shared import reset_mcp_process_state

__all__ = ["reset_mcp_process_state"]
