"""W7.1 — machine-readable health endpoint for server deployments (#381).

Intended public API (W7.2): ``mergecraft.enterprise.health``.
Distinct from the MCP FastAPI ``/health`` probe.
"""

from __future__ import annotations


def test_healthz_path_is_not_mcp_health() -> None:
    """Happy: enterprise health is ``/healthz``, not the MCP ``/health`` route."""
    from mergecraft.enterprise.health import HEALTHZ_PATH

    assert HEALTHZ_PATH == "/healthz"
    assert HEALTHZ_PATH != "/health"


def test_health_payload_is_machine_readable() -> None:
    """Happy: the payload is JSON-shaped with a status field."""
    from mergecraft.enterprise.health import health_payload

    payload = health_payload()
    assert isinstance(payload, dict)
    status = str(payload.get("status", "")).casefold()
    assert status in {"ok", "healthy"}


def test_health_app_serves_healthz() -> None:
    """Integration: the health ASGI app answers GET /healthz with JSON."""
    from starlette.testclient import TestClient

    from mergecraft.enterprise.health import build_health_app

    client = TestClient(build_health_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert str(payload.get("status", "")).casefold() in {"ok", "healthy"}


def test_health_app_unknown_path_is_not_ok() -> None:
    """Error: a missing path is not reported as healthy."""
    from starlette.testclient import TestClient

    from mergecraft.enterprise.health import build_health_app

    client = TestClient(build_health_app())
    response = client.get("/not-a-health-route")
    assert response.status_code >= 400
