"""Process-wide MCP state that must not leak across tests under xdist (#421 / D4)."""

from __future__ import annotations

from mergecraft.mcp.shell import reset_detection_cache


def reset_mcp_process_state() -> None:
    """Reset module-level MCP caches so parallel tests do not share state.

    Called from ``tests/mcp/conftest.py`` (autouse) and available for explicit
    resets when a test starts an MCP HTTP server.
    """
    reset_detection_cache()
