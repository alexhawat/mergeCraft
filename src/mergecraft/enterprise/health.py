"""Machine-readable health payload for enterprise / server deployments (#381).

Distinct from the MCP FastAPI ``/health`` probe.

Scope: this is a *liveness* signal plus the resolved telemetry mode — it
reports the Python runtime and the telemetry sink the process would export to.
It is **not a readiness probe**: it opens no network connection and runs no
dependency check, so nothing here is computable as a failing state without a
live upstream. The aggregate ``status`` is ``ok`` when the process is up and
telemetry resolves.

Exports:
    health_payload: Return a JSON-serialisable dict with a ``status`` field.
"""

from __future__ import annotations

from typing import Any

__all__ = [
    "health_payload",
]


def health_payload() -> dict[str, Any]:
    """Return the liveness + resolved-telemetry-mode payload.

    Returns:
        A dict containing ``status`` plus a ``checks`` map (Python runtime
        and bound telemetry mode). ``status`` is ``ok`` — this is a liveness
        signal, not a readiness probe, and no failing state is computable
        without a live check.
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
