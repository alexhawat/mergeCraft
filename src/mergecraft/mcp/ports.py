"""Port-selection helpers for the MCP HTTP server.

Extracted from ``server.py`` so that CLI commands (``doctor``, ``mcp serve``)
can read the env var or probe a port without importing the FastAPI/uvicorn
server stack.

Uvicorn binds with ``port=0`` for OS assignment; reading the bound port back
requires walking ``server.servers[*].sockets`` (version-sensitive — see
:func:`_bound_port_from_uvicorn_server`). When that graph is absent, callers
must rely on :func:`wait_for_bound_port` polling or an explicit
``MERGECRAFT_MCP_PORT``.
"""

from __future__ import annotations

import os
import socket
import time
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    import uvicorn

MCP_HOST = "127.0.0.1"
_DEFAULT_BIND_WAIT_TIMEOUT_S = 2.5
_DEFAULT_BIND_POLL_INTERVAL_S = 0.05


def read_env_port() -> int | None:
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


def port_available(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((MCP_HOST, port))
        except OSError:
            return False
    return True


def resolve_uvicorn_bind_port() -> int:
    """Return explicit env port when free, otherwise ``0`` for OS assignment at bind."""
    requested = read_env_port()
    if requested is not None:
        if port_available(requested):
            return requested
        logger.warning(
            "MERGECRAFT_MCP_PORT={} is busy; falling back to port 0 for OS assignment",
            requested,
        )
    return 0


def select_port() -> int:
    """Return a listen port for CLI preview before uvicorn starts.

    When ``MERGECRAFT_MCP_PORT`` is unset, briefly reserves an ephemeral port so
    the CLI can print a concrete URL. The MCP HTTP server itself binds with
    ``port=0`` via :func:`resolve_uvicorn_bind_port` to avoid a TOCTOU gap
    between release and uvicorn's bind.
    """
    resolved = resolve_uvicorn_bind_port()
    if resolved != 0:
        return resolved
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((MCP_HOST, 0))
        return sock.getsockname()[1]


def _bound_port_from_uvicorn_server(server: uvicorn.Server, configured_port: int) -> int:
    """Read the bound TCP port from uvicorn's internal server graph (version-sensitive)."""
    import uvicorn as uvicorn_mod

    version = getattr(uvicorn_mod, "__version__", "unknown")
    servers = getattr(server, "servers", None)
    if servers is None:
        msg = (
            f"uvicorn {version} server object has no `servers` attribute; "
            "cannot introspect bound listen port"
        )
        raise RuntimeError(msg)

    for asyncio_server in servers:
        sockets = getattr(asyncio_server, "sockets", None)
        if not sockets:
            continue
        for sock in sockets:
            try:
                _host, port = sock.getsockname()[:2]
            except OSError:
                continue
            if port:
                return int(port)

    if configured_port != 0:
        return configured_port
    msg = "MCP HTTP server started without a bound listen port"
    raise RuntimeError(msg)


def bound_listen_port(server: uvicorn.Server, configured_port: int) -> int:
    """Return the TCP port uvicorn bound (handles explicit ports and ``port=0``)."""
    return _bound_port_from_uvicorn_server(server, configured_port)


def wait_for_bound_port(
    server: uvicorn.Server,
    bind_port: int,
    *,
    host: str = MCP_HOST,
    timeout_s: float = _DEFAULT_BIND_WAIT_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_BIND_POLL_INTERVAL_S,
) -> int:
    """Poll until uvicorn binds, returning the resolved listen port."""
    port = bind_port
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if getattr(server, "started", False):
            try:
                port = bound_listen_port(server, bind_port)
            except RuntimeError:
                pass
            else:
                return port
        if bind_port != 0:
            try:
                with socket.create_connection((host, bind_port), timeout=0.1):
                    return bind_port
            except OSError:
                pass
        time.sleep(poll_interval_s)
    return bound_listen_port(server, bind_port)
