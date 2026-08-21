"""Machine-readable health endpoint for enterprise / server deployments (#381).

Distinct from the MCP FastAPI ``/health`` probe.

Exports:
    HEALTHZ_PATH: The canonical enterprise health path (``/healthz``).
    health_payload: Return a JSON-serialisable dict with a ``status`` field.
    build_health_app: Build a minimal Starlette ASGI app serving ``/healthz``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

if TYPE_CHECKING:
    from starlette.requests import Request

__all__ = [
    "HEALTHZ_PATH",
    "build_health_app",
    "health_payload",
]

HEALTHZ_PATH: str = "/healthz"


def health_payload() -> dict[str, Any]:
    """Return a JSON-serialisable health payload.

    Returns:
        A dict containing at least ``{"status": "ok"}``.
    """
    return {"status": "ok"}


async def _healthz(request: Request) -> Response:
    return JSONResponse(health_payload())


async def _not_found(request: Request, exc: Exception) -> Response:
    return JSONResponse({"detail": "not found"}, status_code=404)


def build_health_app() -> Starlette:
    """Build a minimal Starlette ASGI app that answers ``GET /healthz``.

    Returns:
        A Starlette application with a single ``/healthz`` route.
        All other paths return 404.
    """
    return Starlette(
        routes=[Route(HEALTHZ_PATH, _healthz, methods=["GET"])],
        exception_handlers={404: _not_found},
    )
