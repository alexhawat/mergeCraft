"""Direct unit tests for ``mergecraft.tracing.exporters`` (G5.1 / G-F10).

``tests/tracing/`` had 11 test modules exercising the JSONL sink and the
OTLP exporter transitively (via ``tests/tracing/exporters/`` integration
suites and the sink-lifecycle tests); none named ``test_exporters.py``
targeted the local-sink round-trip, the double-redaction boundary, and the
OTLP attribute mapping directly as unit-level contracts. This file closes
that gap. All five tests here characterise existing behaviour and are green
today.

The two OTLP-mapping tests inject a fake tracer directly into ``OTLPSink``
(``sink._tracer = ...``, bypassing ``_ensure_provider()``'s real
``opentelemetry`` SDK setup) rather than going through ``sink_factory`` +
the process-wide ``TracerProvider`` singleton every ``tests/tracing/exporters/``
integration test shares. Two reasons:

1. It keeps these genuinely unit-level (`OTLPSink.write`'s own attribute
   mapping, in isolation) rather than integration-level, and needs neither
   the optional ``[tracing]`` extra nor a fake network transport.
2. ``opentelemetry``'s ``set_tracer_provider`` can only run once per
   process; every existing integration test that hits the "provider already
   set" fallback in ``_setup_tracer_provider`` permanently stacks one more
   ``_RecordingSpanProcessor`` onto the one shared provider for the rest of
   the pytest session (a pre-existing structural property of that fallback
   path, not something introduced here). Two more sink constructions going
   through that path made ``tests/tracing/exporters/test_integration.py::
   test_payload_cap_applies_to_remote_sinks`` — which assumes exactly one
   recorded payload per write — order-dependently flaky. Injecting the
   tracer directly avoids adding to that shared, accumulating global state.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


class _FakeOtelSpan:
    """Minimal stand-in for the object ``opentelemetry``'s ``Tracer.start_span`` returns."""

    def __init__(self) -> None:
        self.ended = False
        self.end_time: int | None = None

    def end(self, *, end_time: int | None = None) -> None:
        self.ended = True
        self.end_time = end_time


class _FakeOtelTracer:
    """Records every ``start_span(name=..., attributes=...)`` call it receives."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def start_span(
        self,
        *,
        name: str,
        attributes: dict[str, Any],
        start_time: int | None = None,
    ) -> _FakeOtelSpan:
        self.calls.append({"name": name, "attributes": dict(attributes), "start_time": start_time})
        return _FakeOtelSpan()


def test_jsonl_sink_round_trips_every_field(
    trace_dir: Path, trace_event_data: dict[str, Any]
) -> None:
    """Every ``TraceEvent`` field survives a JSONLFileSink write + read_jsonl_events read.

    ``trace_event_data`` (``tests/tracing/conftest.py``) covers the full
    shape — ``kind`` / ``span_id`` / ``parent_span_id`` / ``session_id`` /
    ``trace_id`` / ``turn_id`` / ``tier`` / ``ts_start_ns`` / ``ts_end_ns`` /
    ``status`` / ``attrs`` — so an equality check against the fixture pins
    every field at once, not just the ones a narrower test happens to pick.
    """
    from mergecraft.tracing import JSONLFileSink, TraceEvent, read_jsonl_events

    fixed_day = datetime(2026, 8, 9, tzinfo=UTC)
    sink = JSONLFileSink(trace_dir, clock=lambda: fixed_day)
    sink.write(TraceEvent.model_validate(trace_event_data))

    path = trace_dir / "2026-08-09.jsonl"
    read_back = list(read_jsonl_events(path))

    assert len(read_back) == 1
    assert read_back[0] == trace_event_data


def test_jsonl_sink_redacts_on_write_and_on_read(
    trace_dir: Path, trace_event_data: dict[str, Any]
) -> None:
    """The redaction boundary holds on both sides of the JSONL file (D7 double-redaction).

    Write direction: ``RedactingSink`` strips the secret before a byte
    reaches disk (``sinks.py`` D7 — redaction runs once, before fan-out).
    Read direction: ``mergecraft traces show`` re-applies ``redact_attrs``
    when rendering a read-back event (``cli/tracing_cmd.py:240``) as a
    defense-in-depth pass — this is asserted directly against a raw
    (unredacted) line so the read-side pass is pinned independently of
    whether the write side already caught it.
    """
    from mergecraft.tracing import JSONLFileSink, RedactingSink, TraceEvent, read_jsonl_events
    from mergecraft.tracing.redaction import redact_attrs

    secret = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    trace_event_data["attrs"] = {"message": f"token={secret}"}

    # --- write direction ---------------------------------------------------
    fixed_day = datetime(2026, 8, 9, tzinfo=UTC)
    sink = RedactingSink(JSONLFileSink(trace_dir, clock=lambda: fixed_day))
    sink.write(TraceEvent.model_validate(trace_event_data))

    on_disk = (trace_dir / "2026-08-09.jsonl").read_text(encoding="utf-8")
    assert secret not in on_disk, "RedactingSink must strip the secret before it reaches disk"

    # --- read direction ------------------------------------------------------
    # A raw line written without going through RedactingSink first (simulating
    # data that reached disk unredacted) still gets redacted at render time.
    raw_path = trace_dir / "2026-08-10.jsonl"
    raw_path.write_text(json.dumps(trace_event_data) + "\n", encoding="utf-8")
    raw_events = list(read_jsonl_events(raw_path))
    assert secret in json.dumps(raw_events), "sanity: the raw read itself is not redacted"

    rendered_attrs = redact_attrs(raw_events[0]["attrs"])
    assert secret not in json.dumps(rendered_attrs), (
        "redact_attrs must re-redact even an unredacted read-back event"
    )


def test_otlp_sink_maps_attrs_to_genai_conventions(trace_event_data: dict[str, Any]) -> None:
    """A ``TraceEvent``'s GenAI attrs land unchanged on the exported OTel span (PR #137).

    ``OTLPSink.write`` forwards every ``event.attrs`` key onto the OTel
    span's ``attributes`` (``exporters.py:537-539``) — this pins that the
    ``gen_ai.*`` semantic-convention keys an emit site sets (mirrored in
    ``tests/tracing/test_genai_span_attrs.py``) actually reach the call the
    sink makes into the OTel tracer. A fake tracer is injected directly (see
    the module docstring) so this stays a true unit test of the mapping,
    independent of the real SDK / process-wide provider.
    """
    from mergecraft.tracing import OTLPSink, TraceEvent

    trace_event_data["attrs"] = {
        "gen_ai.system": "anthropic",
        "gen_ai.operation.name": "chat",
        "gen_ai.request.model": "claude-sonnet-5",
        "gen_ai.usage.input_tokens": 120,
        "gen_ai.usage.output_tokens": 48,
    }
    sink = OTLPSink(endpoint="http://127.0.0.1:1/canary-no-network", provider=object())
    fake_tracer = _FakeOtelTracer()
    sink._tracer = fake_tracer  # bypass _ensure_provider(); provider= already short-circuits it

    sink.write(TraceEvent.model_validate(trace_event_data))

    assert len(fake_tracer.calls) == 1
    span_attrs = fake_tracer.calls[0]["attributes"]
    assert span_attrs["gen_ai.system"] == "anthropic"
    assert span_attrs["gen_ai.operation.name"] == "chat"
    assert span_attrs["gen_ai.request.model"] == "claude-sonnet-5"
    assert span_attrs["gen_ai.usage.input_tokens"] == 120
    assert span_attrs["gen_ai.usage.output_tokens"] == 48


def test_otlp_sink_json_encodes_dict_and_list_attrs(trace_event_data: dict[str, Any]) -> None:
    """A dict/list-of-dict attr value is JSON-encoded before it reaches the OTel span.

    ``tool.arguments`` / ``tool.output`` (``_tool_attrs.py``) carry raw dict
    payloads through ``TraceEvent.attrs`` — JSON-compatible, but not one of
    the types the real OTel SDK accepts for span attributes (``bool`` /
    ``str`` / ``bytes`` / ``int`` / ``float`` or a homogeneous sequence of
    those). Passing a dict straight through used to make the SDK log
    "Invalid type dict for attribute" and silently drop the attribute.
    ``OTLPSink.write`` must coerce it via ``_otel_safe_attr_value`` first. A
    scalar-only list (``tool.input_keys``) is left untouched since OTel
    already accepts it.
    """
    from mergecraft.tracing import OTLPSink, TraceEvent

    trace_event_data["attrs"] = {
        "tool.arguments": {"path": "src/foo.py", "content": "x = 1"},
        "tool.output": [{"kind": "text", "text": "ok"}],
        "tool.input_keys": ["content", "path"],
    }
    sink = OTLPSink(endpoint="http://127.0.0.1:1/canary-no-network", provider=object())
    fake_tracer = _FakeOtelTracer()
    sink._tracer = fake_tracer

    sink.write(TraceEvent.model_validate(trace_event_data))

    span_attrs = fake_tracer.calls[0]["attributes"]
    assert isinstance(span_attrs["tool.arguments"], str)
    assert json.loads(span_attrs["tool.arguments"]) == {
        "path": "src/foo.py",
        "content": "x = 1",
    }
    assert isinstance(span_attrs["tool.output"], str)
    assert json.loads(span_attrs["tool.output"]) == [{"kind": "text", "text": "ok"}]
    assert span_attrs["tool.input_keys"] == ["content", "path"]


def test_sink_write_failure_never_propagates(trace_event_data: dict[str, Any]) -> None:
    """A raising inner sink is swallowed by ``RedactingSink`` and logged at ``warning``.

    ``RedactingSink.write`` (``sinks.py:187-193``, retagged onto this module
    at import time — ``_retag_wrappers_as_exporters``, #56 D5) wraps the
    inner ``write`` call in try/except so one misbehaving sink never reaches
    the caller (convention 6). Mirrors the ``MultiSink`` characterisation in
    ``tests/tracing/test_sinks.py`` but pins the wrapper this module owns.
    """
    import loguru

    from mergecraft.tracing import RedactingSink, TraceEvent

    class RaisingInner:
        def write(self, event: TraceEvent) -> None:
            raise OSError("trace disk unavailable")

    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(record.record["message"]), level="WARNING"
    )
    try:
        sink = RedactingSink(RaisingInner())
        sink.write(TraceEvent.model_validate(trace_event_data))  # must not raise
    finally:
        loguru.logger.remove(sink_id)

    assert any("trace disk unavailable" in message for message in captured)


def test_attrs_over_cap_are_truncated_not_dropped(trace_event_data: dict[str, Any]) -> None:
    """An oversized ``attrs`` value is replaced with ``{"truncated": True}``, not dropped.

    ``TRACE_ATTRS_JSON_MAX_BYTES`` (``tracing/cap.py:18``) is the boundary
    ``cap_event_attrs`` enforces before any sink writes an event
    (``RedactingSink.write`` applies it — ``sinks.py:189``); ``OTLPSink.write``
    additionally forwards the marker onto the exported span's attributes
    (``exporters.py:542-543``) so the truncation is visible downstream, not
    silently swallowed with the rest of ``attrs``. Composes the real
    ``RedactingSink`` (the D7 cap boundary) with an ``OTLPSink`` whose
    tracer is faked (see the module docstring) so the whole pipeline is
    exercised without the real SDK / process-wide provider.
    """
    from mergecraft.tracing import TRACE_ATTRS_JSON_MAX_BYTES, OTLPSink, RedactingSink, TraceEvent

    trace_event_data["attrs"] = {"payload": "x" * (TRACE_ATTRS_JSON_MAX_BYTES + 1)}
    sink = OTLPSink(endpoint="http://127.0.0.1:1/canary-no-network", provider=object())
    fake_tracer = _FakeOtelTracer()
    sink._tracer = fake_tracer
    wrapped = RedactingSink(sink)  # applies cap_event_attrs before delegating (D7 / sinks.py:189)

    wrapped.write(TraceEvent.model_validate(trace_event_data))

    assert len(fake_tracer.calls) == 1
    span_attrs = fake_tracer.calls[0]["attributes"]
    assert span_attrs.get("truncated") is True
    assert "payload" not in span_attrs, "the oversized value must not survive truncation"


__all__ = [
    "test_attrs_over_cap_are_truncated_not_dropped",
    "test_jsonl_sink_redacts_on_write_and_on_read",
    "test_jsonl_sink_round_trips_every_field",
    "test_otlp_sink_json_encodes_dict_and_list_attrs",
    "test_otlp_sink_maps_attrs_to_genai_conventions",
    "test_sink_write_failure_never_propagates",
]
