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

import json
import os
import socket
import time
from typing import TYPE_CHECKING

import httpx
from loguru import logger

if TYPE_CHECKING:
    import uvicorn

MCP_HOST = "127.0.0.1"
_DEFAULT_BIND_WAIT_TIMEOUT_S = 2.5
_DEFAULT_BIND_POLL_INTERVAL_S = 0.05
_SERVE_ERRORS_ATTR = "mergecraft_serve_errors"


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


def _serve_errors(server: uvicorn.Server) -> list[BaseException]:
    errors = getattr(server, _SERVE_ERRORS_ATTR, None)
    if isinstance(errors, list):
        return errors
    return []


def _raise_serve_error(server: uvicorn.Server) -> None:
    errors = _serve_errors(server)
    if not errors:
        return
    exc = errors[0]
    if isinstance(exc, RuntimeError):
        raise exc
    if isinstance(exc, OSError):
        raise exc
    if isinstance(exc, SystemExit):
        msg = "MCP HTTP server startup failed"
        raise RuntimeError(msg) from exc
    raise RuntimeError(str(exc)) from exc


def _health_identity_ok(host: str, port: int, health_nonce: str) -> bool:
    url = f"http://{host}:{port}/health?nonce={health_nonce}"
    try:
        with httpx.Client(timeout=0.25) as client:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, json.JSONDecodeError, ValueError):
        return False
    return payload.get("status") == "ok" and payload.get("nonce") == health_nonce


def wait_for_bound_port(
    server: uvicorn.Server,
    bind_port: int,
    *,
    host: str = MCP_HOST,
    timeout_s: float = _DEFAULT_BIND_WAIT_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_BIND_POLL_INTERVAL_S,
    health_nonce: str | None = None,
) -> int:
    """Poll until uvicorn binds, returning the resolved listen port."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        _raise_serve_error(server)
        if getattr(server, "started", False):
            try:
                port = bound_listen_port(server, bind_port)
            except RuntimeError:
                pass
            else:
                if health_nonce is not None and not _health_identity_ok(host, port, health_nonce):
                    time.sleep(poll_interval_s)
                    continue
                return port
        time.sleep(poll_interval_s)
    _raise_serve_error(server)
    port = bound_listen_port(server, bind_port)
    if health_nonce is not None and not _health_identity_ok(host, port, health_nonce):
        msg = "MCP HTTP /health identity check failed"
        raise RuntimeError(msg)
    return port


def attach_serve_error_sink(server: uvicorn.Server) -> list[BaseException]:
    """Attach a list on *server* that the serve thread records exceptions into."""
    errors: list[BaseException] = []
    setattr(server, _SERVE_ERRORS_ATTR, errors)
    return errors
