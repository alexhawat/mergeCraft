"""Machine-readable health payload for enterprise / server deployments (#381).

Distinct from the MCP FastAPI ``/health`` probe.

Exports:
    health_payload: Return a JSON-serialisable dict with a ``status`` field.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "health_payload",
]


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
