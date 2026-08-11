"""RED contracts for one ``trace_id`` per run + OTel context bridge (T3.1).

Wave: ``issues-tracing-sevn-quality`` / PR T3 — ``feat(tracing): one trace_id per
run + OTel context bridge``.

Contract
--------
Every span emitted by a single ``mergecraft diff-review`` run shares one
``trace_id``; the OTel context bridge (a new ``mergecraft.tracing.otel_bridge``
module) propagates that ``trace_id`` so nested OTel auto-instrumented
operations (e.g. an httpx call inside a tool) inherit it without the caller
having to know about mergeCraft's tracer.

These tests are RED against ``origin/pre-0.0.1`` because the implementation
does not exist yet:

- ``src/mergecraft/tracing/event.py`` — ``TraceEvent.trace_id`` is missing.
- ``src/mergecraft/tracing/tracer.py`` — ``Tracer.trace_id``, ``Span.trace_id``,
  ``NullTracer.trace_id``, and ``resolve_trace_id()`` are missing.
- ``src/mergecraft/tracing/otel_bridge.py`` — the module itself is missing.
- ``src/mergecraft/tracing/exporters.py`` — ``OTLPSink.write`` does not yet
  set the real OTel ``trace_id`` on the produced span, and the
  ``_RecordingSpanProcessor`` does not yet capture ``trace_id``.
- ``tests/tracing/conftest.py`` — ``trace_event_data`` lacked ``trace_id``
  until T3.1 landed (see the fixture edit).

Acceptance (after T3.2 lands): **11 collected; 10 green; 1 xfailed** — the
single xfail is ``test_otel_sink_forwards_real_trace_id`` because the
recording-processor's ``trace_id`` capture is the last T3.2 surface to land.
The other 10 tests turn green the moment T3.2 ships
``Tracer.trace_id``/``Span.trace_id``/``TraceEvent.trace_id`` and the
``otel_bridge.attach_trace_context`` body.

The xfail marker is ``strict=False`` so an unsatisfied xfail never hard-fails
the suite (the T3.2 impl wave is allowed to turn tests green on touch).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from pathlib import Path


_TRACE_ID_ENV_KEYS = (
    "MERGECRAFT_TRACE_ID",
    "MERGECRAFT_TRACE_SESSION_ID",
    "GITHUB_RUN_ID",
)


def _strip_trace_id_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every precedence-layer env var so a test starts from a clean slate."""
    for key in _TRACE_ID_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


# ---------------------------------------------------------------------------
# Test 1 — env precedence: ``MERGECRAFT_TRACE_SESSION_ID`` wins.
# ---------------------------------------------------------------------------


def test_trace_id_resolves_to_session_id_when_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``MERGECRAFT_TRACE_SESSION_ID=abc`` → ``Tracer.trace_id == "abc"``.

    The plan's ``resolve_trace_id`` precedence (D7 / T3.2):

    1. ``MERGECRAFT_TRACE_ID``
    2. ``MERGECRAFT_TRACE_SESSION_ID`` (alias — keeps the #56 contract)
    3. ``GITHUB_RUN_ID``
    4. ``uuid.uuid4().hex``
    """
    _strip_trace_id_env(monkeypatch)
    monkeypatch.setenv("MERGECRAFT_TRACE_SESSION_ID", "abc")

    from mergecraft.tracing import Tracer

    tracer = Tracer(sink=object(), session_id="session", run_id="run")
    assert tracer.trace_id == "abc"


# ---------------------------------------------------------------------------
# Test 2 — env precedence: ``GITHUB_RUN_ID`` fills when ``MERGECRAFT_TRACE_*``
# is unset.
# ---------------------------------------------------------------------------


def test_trace_id_falls_back_to_github_run_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """``GITHUB_RUN_ID=123`` → ``Tracer.trace_id == "123"``."""
    _strip_trace_id_env(monkeypatch)
    monkeypatch.setenv("GITHUB_RUN_ID", "123")

    from mergecraft.tracing import Tracer

    tracer = Tracer(sink=object(), session_id="123", run_id="123")
    assert tracer.trace_id == "123"


# ---------------------------------------------------------------------------
# Test 3 — env precedence: ``uuid4()`` fallback when no env vars are set.
# ---------------------------------------------------------------------------


def test_trace_id_is_uuid4_when_no_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """All env unset → 32-hex (uuid4 without dashes)."""
    _strip_trace_id_env(monkeypatch)

    from mergecraft.tracing import Tracer

    tracer = Tracer(sink=object(), session_id="s", run_id="r")
    # 32 hex chars (uuid4().hex); valid hex parses as int.
    assert len(tracer.trace_id) == 32
    int(tracer.trace_id, 16)


# ---------------------------------------------------------------------------
# Test 4 — root + child spans in one run share ``trace_id``.
# ---------------------------------------------------------------------------


def test_all_spans_in_one_run_share_trace_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Open root + child ``with`` blocks; both events have the same ``trace_id``."""
    _strip_trace_id_env(monkeypatch)

    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="session", run_id="run")
    with tracer.start_span("mergecraft.run"), tracer.start_span("mergecraft.publish"):
        pass

    trace_ids = {event.trace_id for event in sink.events}
    assert trace_ids == {tracer.trace_id}
    assert len(sink.events) == 2


# ---------------------------------------------------------------------------
# Test 5 — two separate ``Tracer()`` constructions produce distinct trace_ids.
# ---------------------------------------------------------------------------


def test_two_separate_runs_get_different_trace_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two ``Tracer()`` builds in one process get distinct uuid4 trace_ids."""
    _strip_trace_id_env(monkeypatch)

    from mergecraft.tracing import Tracer

    first = Tracer(sink=object(), session_id="session", run_id="run")
    second = Tracer(sink=object(), session_id="session", run_id="run")
    assert first.trace_id != second.trace_id


# ---------------------------------------------------------------------------
# Test 6 — ``attach_trace_context`` propagates the mergeCraft ``trace_id``
# onto a nested OTel span. Pinned against the new
# ``mergecraft.tracing.otel_bridge`` module (T3.2 file 3).
# ---------------------------------------------------------------------------


def test_attach_trace_context_makes_nested_otel_span_share_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inside ``with attach_trace_context(span):`` the OTel ``trace_id`` matches."""
    pytest.importorskip("opentelemetry")
    _strip_trace_id_env(monkeypatch)

    # T3.2 file 3 ships this module; the import is the failing surface until
    # then. ``pytest.importorskip`` keeps collection clean in environments
    # where the module is absent (the test will surface as FAILED, not a
    # collection error, when OTel is installed but the module is missing).
    from opentelemetry import trace as otel_trace

    from mergecraft.tracing import Tracer
    from mergecraft.tracing.otel_bridge import attach_trace_context

    tracer = Tracer(sink=object(), session_id="session", run_id="run")
    with tracer.start_span("mergecraft.run") as span, attach_trace_context(span):
        current = otel_trace.get_current_span()
        otel_trace_id = current.get_span_context().trace_id
        assert otel_trace_id == int(span.trace_id[:32], 16)
        assert format(otel_trace_id, "032x") == span.trace_id


# ---------------------------------------------------------------------------
# Test 7 — disabled path: ``NullTracer`` exposes ``trace_id=""``; no event is
# ever emitted.
# ---------------------------------------------------------------------------


def test_disabled_path_emits_no_trace_id() -> None:
    """``NullTracer.trace_id`` is the empty string; no span ever reaches a sink."""
    from mergecraft.tracing import NullTracer

    null = NullTracer()
    assert null.trace_id == ""
    # ``NullSpan`` is a context manager that swallows state but never writes
    # — no exception, no event.
    with null.start_span("mergecraft.run") as span:
        span.set_attribute("unused", True)


# ---------------------------------------------------------------------------
# Test 8 — ``JSONLFileSink`` round-trip preserves ``trace_id`` on every line.
# ---------------------------------------------------------------------------


def test_jsonl_sink_includes_trace_id(trace_dir: Path) -> None:
    """JSONL round-trip includes ``trace_id`` in every emitted line."""
    from mergecraft.tracing import JSONLFileSink, TraceEvent

    sink = JSONLFileSink(trace_dir)
    trace_id_hex = "deadbeef" * 4  # 32 hex chars
    event = TraceEvent.model_validate(
        {
            "kind": "llm.call",
            "span_id": "span-jsonl",
            "parent_span_id": None,
            "session_id": "run",
            "turn_id": "turn",
            "tier": "trusted",
            "ts_start_ns": 1_000,
            "ts_end_ns": 2_000,
            "status": "ok",
            "attrs": {},
            "trace_id": trace_id_hex,
        }
    )
    sink.write(event)

    jsonl_files = sorted(trace_dir.glob("*.jsonl"))
    assert len(jsonl_files) == 1
    payload = json.loads(jsonl_files[0].read_text(encoding="utf-8").strip())
    assert payload["trace_id"] == trace_id_hex


# ---------------------------------------------------------------------------
# Test 9 — ``OTLPSink`` forwards the real OTel ``trace_id`` on the produced
# span, and ``_RecordingSpanProcessor`` captures it. Pinned via the existing
# test seam in ``src/mergecraft/tracing/exporters.py``.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    reason="green after T3.2: OTel trace_id set on span + recording capture",
    strict=False,
)
def test_otel_sink_forwards_real_trace_id(trace_event_payload: dict[str, Any]) -> None:
    """OTLPSink writes a span whose OTel ``trace_id`` matches ``event.trace_id``."""
    pytest.importorskip("opentelemetry")

    from mergecraft.config import RepoSettings
    from mergecraft.tracing import TraceEvent, sink_factory
    from mergecraft.tracing.exporters import captured_payload

    settings = RepoSettings.model_validate(
        {
            "tracing": {
                "enabled": True,
                "sinks": [
                    {
                        "type": "otel",
                        "endpoint": "http://127.0.0.1:1/canary-no-network",
                        "headers": {},
                    }
                ],
            }
        }
    ).tracing
    sink = sink_factory(settings)

    trace_id_hex = "0123456789abcdef" * 2  # 32 hex chars (OTel trace_id is 128 bits)
    event = TraceEvent.model_validate(trace_event_payload | {"trace_id": trace_id_hex})
    sink.write(event)
    sink.flush()

    payloads = captured_payload()
    assert payloads, "OTLPSink did not capture any spans via _RecordingSpanProcessor"
    # ``_RecordingSpanProcessor.on_end`` writes JSON arrays per span; the
    # T3.2 update surfaces ``trace_id`` on the captured payload so the
    # Logfire-grouping contract is observable through the existing seam.
    parsed = json.loads(b"".join(payloads).decode("utf-8"))
    assert int(parsed[0]["trace_id"], 16) == int(trace_id_hex, 16)


# ---------------------------------------------------------------------------
# Test 10 — ``tests/tracing/conftest.py::trace_event_data`` now includes
# ``trace_id``; the round-trip equality holds.
# ---------------------------------------------------------------------------


def test_trace_id_field_added_to_trace_event_data_fixture(
    trace_event_data: dict[str, Any],
) -> None:
    """``trace_event_data`` carries ``trace_id`` and round-trips through ``TraceEvent``."""
    assert "trace_id" in trace_event_data

    from mergecraft.tracing import TraceEvent

    event = TraceEvent.model_validate(trace_event_data)
    assert event.model_dump() == trace_event_data


# ---------------------------------------------------------------------------
# Test 11 — regression: every fixture in ``tests/tracing/conftest.py`` still
# round-trips through ``TraceEvent`` after the ``trace_id`` addition.
# ---------------------------------------------------------------------------


def test_existing_fixtures_remain_green(
    fake_attrs: dict[str, Any], trace_event_data: dict[str, Any]
) -> None:
    """The full ``tests/tracing`` conftest suite still round-trips after T3.2."""
    from mergecraft.tracing import TraceEvent

    # ``trace_event_data`` includes ``trace_id`` after T3.2 conftest update.
    assert "trace_id" in trace_event_data
    event = TraceEvent.model_validate(trace_event_data)
    assert event.model_dump() == trace_event_data

    # An explicit ``trace_id`` payload also round-trips (sentinel).
    payload = {
        "kind": "llm.call",
        "span_id": "span-1",
        "parent_span_id": None,
        "session_id": "run-1",
        "turn_id": "turn-1",
        "tier": "trusted",
        "ts_start_ns": 1_000,
        "ts_end_ns": 2_000,
        "status": "ok",
        "attrs": fake_attrs,
        "trace_id": "trace-smoke-0001",
    }
    explicit = TraceEvent.model_validate(payload)
    assert explicit.model_dump() == payload


__all__ = [
    "test_all_spans_in_one_run_share_trace_id",
    "test_attach_trace_context_makes_nested_otel_span_share_trace_id",
    "test_disabled_path_emits_no_trace_id",
    "test_existing_fixtures_remain_green",
    "test_jsonl_sink_includes_trace_id",
    "test_otel_sink_forwards_real_trace_id",
    "test_trace_id_falls_back_to_github_run_id",
    "test_trace_id_field_added_to_trace_event_data_fixture",
    "test_trace_id_is_uuid4_when_no_env",
    "test_trace_id_resolves_to_session_id_when_set",
    "test_two_separate_runs_get_different_trace_ids",
]
