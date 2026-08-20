"""Port-selection helpers for the MCP HTTP server.

Extracted from ``server.py`` so that CLI commands (``doctor``, ``mcp serve``)
can read the env var or probe a port without importing the FastAPI/uvicorn
server stack.
"""

from __future__ import annotations

import os
import socket

MCP_HOST = "127.0.0.1"


def _read_env_port() -> int | None:
    raw = os.environ.get("MERGECRAFT_MCP_PORT")
    if not raw:
        return None
    try:
        parsed = int(raw)
    except ValueError as err:
        msg = f"invalid MERGECRAFT_MCP_PORT: {raw}"
        raise ValueError(msg) from err
    if parsed <= 0 or parsed > 65535:
        msg = f"invalid MERGECRAFT_MCP_PORT: {raw}"
        raise ValueError(msg)
    return parsed


def _port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((MCP_HOST, port))
        except OSError:
            return False
    return True


def _select_port() -> int:
    requested = _read_env_port()
    if requested is not None and _port_available(requested):
        return requested
    # Let the OS allocate an ephemeral port by binding to 0, then release it.
    # A concurrent process could claim the port in the brief window between
    # release and uvicorn's bind, but this is orders of magnitude safer than
    # the old 50-wide scan from a fixed base (which was both predictable and
    # racy in the same way).
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((MCP_HOST, 0))
        return sock.getsockname()[1]
