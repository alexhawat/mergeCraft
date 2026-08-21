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
    """Return a JSON-serialisable health payload with live checks.

    Returns:
        A dict containing ``status`` plus a ``checks`` map (Python runtime
        and bound telemetry mode). ``status`` is ``ok`` when those checks pass.
    """
    from mergecraft.enterprise.diagnostics import operational_diagnostics
    from mergecraft.enterprise.runtime import current_enterprise_settings
    from mergecraft.enterprise.telemetry import (
        is_telemetry_export_enabled,
        resolve_telemetry_mode,
    )

    diag = operational_diagnostics()
    mode = resolve_telemetry_mode(explicit=current_enterprise_settings().telemetry)
    checks: dict[str, Any] = {
        "python": {
            "status": "ok",
            "version": diag.get("python_version_info"),
        },
        "telemetry": {
            "status": "ok",
            "mode": mode.value,
            "remote_export": is_telemetry_export_enabled(mode),
        },
    }
    return {"status": "ok", "checks": checks}


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
