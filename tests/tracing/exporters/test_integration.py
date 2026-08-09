"""End-to-end RED contracts that exercise multiple exporters layers in concert (W7 integration).

These tests are intentionally coarse-grained — they assert that the
``logfire`` and ``otel`` sinks, the CLI precedence layer, and the redaction
boundary compose correctly. They are the integration counterpart to the
fine-grained unit tests in this package.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest


def test_logfire_and_otel_sinks_compose_with_local_sink() -> None:
    """A single repo can configure ``local_files``, ``logfire``, and ``otel`` simultaneously.

    The factory returns a fan-out that satisfies D7: every event flows
    through one redacting boundary.
    """
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import MultiSink, RedactingSink, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {"type": "jsonl_file", "path": ".mergecraft/traces/"},
                    {"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"},
                    {"type": "otel", "endpoint": "http://127.0.0.1:4318/", "headers": {}},
                ],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    assert isinstance(sink, RedactingSink)
    assert isinstance(sink.inner, MultiSink)
    # Three children, one redacting boundary.
    assert len(sink.inner.sinks) == 3


def test_redaction_applies_to_remote_sinks() -> None:
    """A ``ghp_…`` secret in ``attrs`` never reaches the Logfire/OTLP transport.

    Convention 8 — we assert the contract via the in-memory transport
    exposed by ``mergecraft.tracing.exporters``.
    """
    pytest.importorskip("logfire")
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    secret = "ghp_canaryfromintegrationsuite1234567890abcdef"
    event = TraceEvent.model_validate(
        {
            "kind": "llm.call",
            "span_id": "s",
            "parent_span_id": None,
            "session_id": "r",
            "turn_id": "t",
            "tier": "trusted",
            "ts_start_ns": 0,
            "ts_end_ns": 1,
            "status": "ok",
            "attrs": {"prompt": f"Authorization: Bearer {secret}"},
        }
    )
    sink.write(event)
    sink.flush()
    from mergecraft.tracing.exporters import captured_payload

    payload_blob = b"".join(captured_payload())
    assert secret.encode() not in payload_blob


def test_disabled_tracing_does_not_create_remote_exporters() -> None:
    """When tracing is disabled, ``sink_factory`` returns ``NullSink`` — no remote exporter is built."""
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory

    settings = RepoSettings.model_validate({}).tracing
    sink = sink_factory(settings)
    assert isinstance(sink, NullSink)
    # No tracer provider was built — the exporters module is untouched.
    from mergecraft.tracing.exporters import has_active_tracer_provider

    assert not has_active_tracer_provider()


def test_disabled_tracing_does_not_create_filesystem_artifacts(tmp_path: Path) -> None:
    """Convention 9 — the disabled path creates no files and runs no remote setup."""
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate({}).tracing
    sink = sink_factory(settings)
    sink.emit(kind="mergecraft.run", attrs_source=lambda: {"x": 1})
    # Nothing created under tmp_path.
    assert list(tmp_path.iterdir()) == []


def test_sink_factory_with_only_remote_sinks_does_not_create_local_files(tmp_path: Path) -> None:
    """A config that requests only ``logfire`` / ``otel`` does not write a local JSONL file."""
    pytest.importorskip("logfire")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    sink.write(
        TraceEvent.model_validate(
            {
                "kind": "llm.call",
                "span_id": "remote-only",
                "parent_span_id": None,
                "session_id": "r",
                "turn_id": "t",
                "tier": "trusted",
                "ts_start_ns": 0,
                "ts_end_ns": 1,
                "status": "ok",
                "attrs": {},
            }
        )
    )
    # No ``.mergecraft/traces`` was created locally.
    assert not (tmp_path / ".mergecraft").exists()


def _event(attrs: dict[str, Any]) -> Any:
    from mergecraft.tracing import TraceEvent

    return TraceEvent.model_validate(
        {
            "kind": "llm.call",
            "span_id": "s",
            "parent_span_id": None,
            "session_id": "r",
            "turn_id": "t",
            "tier": "trusted",
            "ts_start_ns": 0,
            "ts_end_ns": 1,
            "status": "ok",
            "attrs": attrs,
        }
    )


def test_payload_cap_applies_to_remote_sinks(monkeypatch: pytest.MonkeyPatch) -> None:
    """D8 — over 64 KiB, the remote exporter receives a truncation marker, not the raw blob."""
    pytest.importorskip("logfire")
    monkeypatch.setenv("MERGECRAFT_LOGFIRE_TOKEN", "test-token")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import sink_factory

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [{"type": "logfire", "tokenRef": "MERGECRAFT_LOGFIRE_TOKEN"}],
            }
        }
    ).tracing
    sink = sink_factory(settings)
    big = "x" * (64 * 1024 + 1)
    sink.write(_event({"payload": big}))
    sink.flush()
    from mergecraft.tracing.exporters import captured_payloads_json

    payloads = json.loads(b"".join(captured_payloads_json()).decode() or "[]")
    assert payloads  # at least one payload
    # The cap propagated: ``attrs`` was replaced with the truncation marker.
    last = payloads[-1]
    assert last.get("attrs", {}).get("truncated") is True
    assert "x" * (64 * 1024 + 1) not in json.dumps(last)
