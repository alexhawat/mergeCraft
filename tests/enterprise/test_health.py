"""W7.1 — machine-readable health payload for server deployments (#381).

Intended public API (W7.2): ``mergecraft.enterprise.health``.
Distinct from the MCP FastAPI ``/health`` probe.
"""

from __future__ import annotations


def test_health_payload_is_machine_readable() -> None:
    """Happy: the payload is JSON-shaped with a status field."""
    from mergecraft.enterprise.health import health_payload

    payload = health_payload()
    assert isinstance(payload, dict)
    status = str(payload.get("status", "")).casefold()
    assert status in {"ok", "healthy"}
    checks = payload.get("checks")
    assert isinstance(checks, dict)
    assert "python" in checks
    assert "telemetry" in checks
