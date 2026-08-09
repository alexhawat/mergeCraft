"""RED contracts for local tracing sinks and lifecycle behavior."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path


class RecordingSink:
    def __init__(self) -> None:
        self.events: list[Any] = []

    def write(self, event: Any) -> None:
        self.events.append(event)


class RaisingSink:
    def write(self, event: Any) -> None:
        raise OSError("trace disk unavailable")


def test_jsonl_sink_writes_rotating_daily_files(
    trace_dir: Path, trace_event_data: dict[str, Any]
) -> None:
    from mergecraft.tracing import JSONLFileSink, TraceEvent

    day_one = datetime(2026, 8, 9, 23, 59, tzinfo=UTC)
    sink = JSONLFileSink(trace_dir, clock=lambda: day_one)
    sink.write(TraceEvent.model_validate(trace_event_data))
    sink.clock = lambda: day_one + timedelta(minutes=2)
    sink.write(TraceEvent.model_validate(trace_event_data | {"span_id": "span-2"}))

    files = sorted(trace_dir.glob("*.jsonl"))
    assert [path.name for path in files] == ["2026-08-09.jsonl", "2026-08-10.jsonl"]
    assert [json.loads(path.read_text(encoding="utf-8")) for path in files] == [
        trace_event_data,
        trace_event_data | {"span_id": "span-2"},
    ]


def test_jsonl_reader_skips_malformed_lines(trace_dir: Path) -> None:
    from mergecraft.tracing import read_jsonl_events

    trace_dir.mkdir(parents=True)
    path = trace_dir / "2026-08-09.jsonl"
    path.write_text('{"span_id":"valid"}\nnot-json\n', encoding="utf-8")
    assert [event["span_id"] for event in read_jsonl_events(path)] == ["valid"]


def test_multiple_sinks_receive_every_event(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import MultiSink, TraceEvent

    first, second = RecordingSink(), RecordingSink()
    event = TraceEvent.model_validate(trace_event_data)
    MultiSink([first, second]).write(event)
    assert first.events == [event]
    assert second.events == [event]


def test_sink_failure_never_fails_the_run(trace_event_data: dict[str, Any]) -> None:
    from mergecraft.tracing import MultiSink, TraceEvent

    messages: list[str] = []
    sink_id = logger.add(lambda record: messages.append(record.record["message"]), level="WARNING")
    result = {"review": "unchanged"}
    try:
        MultiSink([RaisingSink()]).write(TraceEvent.model_validate(trace_event_data))
    finally:
        logger.remove(sink_id)
    assert result == {"review": "unchanged"}
    assert any("trace disk unavailable" in message for message in messages)


def test_retention_purge_removes_expired_local_traces(trace_dir: Path) -> None:
    from mergecraft.tracing import JSONLFileSink

    trace_dir.mkdir(parents=True)
    expired = trace_dir / "2026-07-09.jsonl"
    retained = trace_dir / "2026-08-09.jsonl"
    expired.touch()
    retained.touch()
    now = datetime(2026, 8, 9, tzinfo=UTC)
    os.utime(expired, (now.timestamp() - 31 * 86_400,) * 2)
    os.utime(retained, (now.timestamp(),) * 2)

    sink = JSONLFileSink(trace_dir, clock=lambda: now)
    assert sink.retention_days == 30
    sink.purge_expired()
    assert not expired.exists()
    assert retained.exists()


def test_tracing_disabled_is_a_true_noop(trace_dir: Path) -> None:
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory

    attrs_calls = 0

    def attrs_source() -> dict[str, Any]:
        nonlocal attrs_calls
        attrs_calls += 1
        return {"unused": True}

    sink = sink_factory(RepoSettings.model_validate({}).tracing)
    assert isinstance(sink, NullSink)
    sink.emit(kind="mergecraft.run", attrs_source=attrs_source)
    assert attrs_calls == 0
    assert not trace_dir.exists()


def test_tracing_disabled_mid_run_takes_null_path(trace_dir: Path) -> None:
    from mergecraft.config import RepoSettings
    from mergecraft.tracing import NullSink, sink_factory

    settings = RepoSettings.model_validate({"tracing": {"enabled": False}})
    sink = sink_factory(settings.tracing)
    assert isinstance(sink, NullSink)
    assert not trace_dir.exists()
