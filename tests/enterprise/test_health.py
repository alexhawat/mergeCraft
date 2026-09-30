"""W7.1 — machine-readable health payload for server deployments (#381).

Intended public API (W7.2): ``mergecraft.enterprise.health``.
Distinct from the MCP FastAPI ``/health`` probe.

CF4.2 — the payload goes through ``cli_json_dumps`` (so it carries
``schema_version``) and the command states its real scope: liveness plus the
resolved telemetry mode, not a readiness probe.
"""

from __future__ import annotations

import json
import re

from typer.testing import CliRunner

from mergecraft.cli.app import app

runner = CliRunner()
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


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


def test_health_payload_names_each_check() -> None:
    """Every check carries a status; telemetry names the resolved mode."""
    from mergecraft.enterprise.health import health_payload

    checks = health_payload()["checks"]
    assert set(checks) == {"python", "telemetry"}
    assert checks["python"]["status"] == "ok"
    telemetry = checks["telemetry"]
    assert telemetry["status"] == "ok"
    assert isinstance(telemetry["mode"], str)
    assert telemetry["mode"], "telemetry mode must be resolved, not empty"


def test_health_cli_output_carries_schema_version() -> None:
    """CF4.2 — the CLI emits the shared schema-versioned JSON envelope."""
    result = runner.invoke(app, ["health"], env=_DUMB_ENV)
    output = _plain(result.stdout + result.stderr)
    assert result.exit_code == 0, output
    payload = json.loads(result.stdout)
    assert payload["schema_version"] == "1.0.0"
    assert payload["status"] == "ok"
    assert "checks" in payload


def test_health_help_states_its_scope() -> None:
    """CF-D4 — the command says what it checks, and what it is not."""
    result = runner.invoke(app, ["health", "--help"], env=_DUMB_ENV)
    output = _plain(result.stdout + result.stderr).lower()
    assert result.exit_code == 0, output
    assert "liveness" in output, output
    assert "telemetry" in output, output
    assert "not a readiness probe" in output, output
