"""Shared fixtures for Batch D exporter tests (W7).

The exporters are reachable through the ``mergecraft.tracing.exporters`` module
that W8 ships — they live behind the optional ``[tracing]`` extra and import
``logfire`` / ``opentelemetry`` lazily (D6). Tests that genuinely need the
exporter classes use :func:`pytest.importorskip` and pin behaviour under the
installed path; tests for the uninstalled path (W7.5) verify the resolver
fails closed without raising an unhandled ``ImportError``.
"""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import pytest


@pytest.fixture
def fake_otel_endpoint() -> str:
    """A loopback URL no test should ever hit — proves there is no live network call."""
    return "http://127.0.0.1:1/canary-no-network"


@pytest.fixture
def free_port() -> int:
    """Find an unused TCP port on the loopback interface.

    Binds an ephemeral socket, reads the assigned port, and closes it; the port
    is "free" at the moment of the call (a small race window is acceptable —
    the test server holds it immediately afterwards).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture
def fake_otel_transport(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Record the bytes the OTLP exporter would have sent — no socket, no network.

    Tests register this fixture and assert on the captured payload. The exporter
    code under test must use an injectable transport (W8.1 — the OTLP
    BatchSpanProcessor accepts a custom ``OTLPExporter``); this fixture is the
    injection point.

    Returns a list (mutable) that the test can read after the run.
    """
    captured: list[bytes] = []

    def _capture(payload: bytes) -> None:
        captured.append(payload)

    monkeypatch.setitem(
        __import__("sys").modules, "__capture__", {"payloads": captured, "send": _capture}
    )
    return captured


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip every mergecraft-related env var so precedence tests start from a clean slate."""
    env_keys = [
        "MERGECRAFT_LOGFIRE_TOKEN",
        "MERGECRAFT_OTEL_ENDPOINT",
        "MERGECRAFT_TRACING",
        "MERGECRAFT_TRACING_TO",
        "MERGECRAFT_TRACE_DIR",
        "MERGECRAFT_CONFIG",
        "INPUT_TRACING",
        "INPUT_TRACING_TO",
        "INPUT_LOGFIRE_TOKEN",
        "INPUT_OTEL_ENDPOINT",
        "GITHUB_WORKSPACE",
    ]
    for key in env_keys:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def trace_event_payload() -> dict[str, Any]:
    """Minimal ``TraceEvent`` payload for exporter smoke tests."""
    return {
        "kind": "llm.call",
        "span_id": "exp-1",
        "parent_span_id": None,
        "session_id": "run-export",
        "turn_id": "turn-export",
        "tier": "trusted",
        "ts_start_ns": 1_700_000_000_000_000_000,
        "ts_end_ns": 1_700_000_000_001_000_000,
        "status": "ok",
        "attrs": {"model.id": "anthropic/claude-sonnet"},
    }


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """A scratch directory masquerading as ``GITHUB_WORKSPACE`` for CLI precedence tests."""
    return tmp_path
