"""RED contracts for the Logfire data-region env var + CLI flag (issue #134 follow-up).

The Logfire OTLP data region (``us`` / ``eu``) must be settable both via the
``MERGECRAFT_TRACING_REGION`` ``.env`` variable and via
``mergecraft tracing logfire enable --region <region>``. The precedence is
CLI ``--region`` > env ``MERGECRAFT_TRACING_REGION`` > YAML ``region``
(default ``us``). The resolved region flows through
:func:`mergecraft.tracing.resolve.resolve_active_tracing` into the
``TraceSinkEntry.region`` field that :func:`_build_logfire_sink` reads.

These tests never touch the real repo ``.env`` — ``MERGECRAFT_ENV`` points the
env-writer helper at a temp file. Tokens are fake (``pylf_test_xxx``).
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from typer.testing import CliRunner

from mergecraft.cli.app import app

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch

runner = CliRunner()

_REGION_ENV = "MERGECRAFT_TRACING_REGION"


def _load_logfire_cmd() -> object:
    try:
        return importlib.import_module("mergecraft.cli.tracing_logfire_cmd")
    except ImportError as exc:  # pragma: no cover
        pytest.fail(f"mergecraft.cli.tracing_logfire_cmd not importable: {exc}")


def _patch_httpx_with(monkeypatch: MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.Client

    def _factory(*args: Any, **kwargs: Any):  # type: ignore[no-untyped-def]
        kwargs.setdefault("transport", transport)
        kwargs.setdefault("timeout", 15.0)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("mergecraft.cli.auth_cmd.httpx.Client", _factory)


def _stub_repo_slug(monkeypatch: MonkeyPatch, slug: str = "acme/widgets") -> None:
    consumer_module = importlib.import_module("mergecraft.cli.tracing_logfire_cmd")

    def _factory() -> str:
        return slug

    monkeypatch.setattr(consumer_module, "_parse_repo_slug", _factory)


def _clear_region_env(monkeypatch: MonkeyPatch) -> None:
    for key in (
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_TO",
        "MERGECRAFT_LOGFIRE_TOKEN",
        "MERGECRAFT_TRACING_PROJECT",
        "MERGECRAFT_OTEL_ENDPOINT",
        "MERGECRAFT_TRACE_DIR",
        _REGION_ENV,
    ):
        monkeypatch.delenv(key, raising=False)


# ── precedence: env var overrides the YAML default ───────────────────────────


def test_env_var_overrides_yaml_default(monkeypatch: MonkeyPatch) -> None:
    """``MERGECRAFT_TRACING_REGION=eu`` → resolved logfire sink region ``eu``."""
    _clear_region_env(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_test_xxx")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "mergecraft-dev")
    monkeypatch.setenv(_REGION_ENV, "eu")

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    assert settings.enabled is True
    assert len(settings.sinks) == 1
    assert settings.sinks[0].type == "logfire"
    assert settings.sinks[0].region == "eu"


def test_default_region_is_us(monkeypatch: MonkeyPatch) -> None:
    """With no env and no config, the resolved logfire region defaults to ``us``."""
    _clear_region_env(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_test_xxx")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "mergecraft-dev")

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing()
    assert settings.sinks[0].region == "us"


def test_cli_flag_overrides_env(monkeypatch: MonkeyPatch) -> None:
    """CLI ``--region eu`` wins over env ``MERGECRAFT_TRACING_REGION=us``."""
    _clear_region_env(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACING", "true")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "pylf_test_xxx")
    monkeypatch.setenv("MERGECRAFT_TRACING_PROJECT", "mergecraft-dev")
    monkeypatch.setenv(_REGION_ENV, "us")

    from mergecraft.tracing.resolve import resolve_active_tracing

    settings = resolve_active_tracing(cli_args=["--region", "eu"])
    assert settings.sinks[0].region == "eu"


# ── CLI: ``enable --region`` writes the env var ──────────────────────────────


def test_cli_region_writes_env(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``enable --region eu`` writes ``MERGECRAFT_TRACING_REGION=eu`` to .env."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"project_name": "acme/widgets"}])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_repo_slug(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "enable",
            "--token",
            "pylf_test_xxx",
            "--project",
            "mergecraft-dev",
            "--region",
            "eu",
        ],
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    written = env_path.read_text(encoding="utf-8")
    # ``python-dotenv`` quotes values (``quote_mode="always"``); accept both
    # quoted and unquoted forms so the assertion matches the writer's output.
    assert f"{_REGION_ENV}=eu" in written or f"{_REGION_ENV}='eu'" in written


def test_cli_region_invalid_rejected(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """``--region de`` is rejected cleanly with a non-zero exit code."""

    def _handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    _patch_httpx_with(monkeypatch, _handler)
    _stub_repo_slug(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_ENV", str(tmp_path / ".env"))
    env_path = tmp_path / ".env"
    env_path.write_text("", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "tracing",
            "logfire",
            "enable",
            "--token",
            "pylf_test_xxx",
            "--project",
            "mergecraft-dev",
            "--region",
            "de",
        ],
    )

    assert result.exit_code != 0
    output = (result.stdout + result.stderr).lower()
    assert "region" in output
    # No env write happened because the region was rejected before writing.
    assert _REGION_ENV not in env_path.read_text(encoding="utf-8")
