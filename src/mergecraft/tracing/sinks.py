"""Sink implementations and the ``sink_factory`` resolver (W2.3).

A *sink* is anything that knows how to ``write(event)`` for a
:class:`mergecraft.tracing.event.TraceEvent`. The hierarchy:

- :class:`NullSink` — no-op. ``emit`` is provided for the disabled-path
  short-circuit (convention 9): the attrs callable is never invoked.
- :class:`JSONLFileSink` — appends to ``<trace_dir>/YYYY-MM-DD.jsonl`` and
  rotates daily via a settable ``clock`` (W1.4). ``retention_days`` (default
  30) drives :meth:`JSONLFileSink.purge_expired` (D8).
- :class:`MemorySink` — in-memory list used by the structural test and
  available for fixtures.
- :class:`MultiSink` — fan-out. Each child write is wrapped in try/except
  (convention 6) so one misbehaving sink never fails the run.
- :class:`RedactingSink` — wraps a sink (including :class:`MultiSink`) and
  redacts :attr:`TraceEvent.attrs` before delegating ``write``. Redaction is
  applied once, before fan-out — D7.

:func:`sink_factory` resolves :class:`mergecraft.config.settings.TracingSettings`
to a live sink. When ``enabled`` is false, it returns a :class:`NullSink`
without touching the filesystem. ``logfire`` and ``otel`` types are not yet
implemented (W8).

Exports:
    NullSink, JSONLFileSink, MemorySink, MultiSink, RedactingSink
    sink_factory, read_jsonl_events
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from loguru import logger

from mergecraft.tracing.cap import cap_event_attrs
from mergecraft.tracing.redaction import redact_event

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from mergecraft.tracing.event import TraceEvent


class _SinkProtocol(Protocol):
    """Structural contract for any sink — kept private to this module."""

    def write(self, event: TraceEvent) -> None: ...


def _now_utc() -> datetime:
    """Return the current UTC datetime — the default ``clock`` for sinks."""
    return datetime.now(UTC)


class NullSink:
    """No-op sink. The disabled path (convention 9) and the test default."""

    def emit(self, kind: str, attrs_source: Callable[[], dict[str, Any]]) -> None:
        """No-op. ``attrs_source`` is intentionally never called (W1.11)."""

    def write(self, event: TraceEvent) -> None:
        """No-op write — kept for parity with the sink protocol."""


class MemorySink:
    """In-memory sink — records every event in a list."""

    def __init__(self) -> None:
        self.events: list[TraceEvent] = []

    def write(self, event: TraceEvent) -> None:
        self.events.append(event)


class JSONLFileSink:
    """Append-only JSONL file sink with daily rotation and retention purge.

    Parameters
    ----------
    trace_dir : Path
        Directory where ``YYYY-MM-DD.jsonl`` files are written.
    clock : Callable[[], datetime], optional
        Returns the current UTC datetime; defaults to :func:`datetime.now`.
        Settable as an attribute so tests can advance the clock.
    """

    def __init__(
        self,
        trace_dir: Path,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.trace_dir = trace_dir
        self.clock = clock if clock is not None else _now_utc
        self.retention_days: int = 30

    def write(self, event: TraceEvent) -> None:
        """Append ``event`` to today's JSONL file (best-effort)."""
        day_str = self.clock().strftime("%Y-%m-%d")
        path = self.trace_dir / f"{day_str}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.model_dump()) + "\n")
        except OSError as exc:
            logger.warning("trace sink JSONLFileSink write failed: {}", exc)

    def purge_expired(self) -> None:
        """Remove ``*.jsonl`` files older than :attr:`retention_days` (mtime)."""
        if not self.trace_dir.exists():
            return
        cutoff = self.clock().timestamp() - self.retention_days * 86_400
        for path in self.trace_dir.glob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError as exc:
                logger.warning("trace sink stat failed for {}: {}", path, exc)
                continue
            if mtime < cutoff:
                try:
                    path.unlink()
                except OSError as exc:
                    logger.warning("trace sink unlink failed for {}: {}", path, exc)


class MultiSink:
    """Fan-out across a fixed list of child sinks.

    Each child's ``write`` is wrapped in a try/except — one failing child
    must never break the others or the caller (convention 6).
    """

    def __init__(self, sinks: list[Any]) -> None:
        self.sinks = list(sinks)

    def write(self, event: TraceEvent) -> None:
        for sink in self.sinks:
            try:
                sink.write(event)
            except Exception as exc:
                logger.warning("trace sink {} failed: {}", type(sink).__name__, exc)


class RedactingSink:
    """Wraps a sink and redacts ``attrs`` before delegating ``write``.

    D7: redaction runs once, before fan-out. The wrapper exposes the inner
    sink as :attr:`inner` so callers (and tests) can assert the structural
    ordering ``RedactingSink(MultiSink([...]))``.
    """

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    def write(self, event: TraceEvent) -> None:
        redacted = redact_event(event)
        capped_attrs = cap_event_attrs(redacted.model_dump())["attrs"]
        try:
            self.inner.write(redacted.model_copy(update={"attrs": capped_attrs}))
        except Exception as exc:
            logger.warning("trace sink write failed: {}", exc)


_DEFAULT_LOCAL_TRACES_PATH = ".mergecraft/traces/"


def sink_factory(tracing_settings: Any) -> Any:
    """Resolve :class:`TracingSettings` to a live sink.

    When ``tracing.enabled`` is false, returns a :class:`NullSink` without
    touching the filesystem (convention 9). Otherwise, builds one sink per
    ``sinks`` entry, wraps them in :class:`MultiSink`, then :class:`RedactingSink`
    (D7). ``logfire`` and ``otel`` are reserved for the ``[tracing]`` extra
    that ships in W8 — until then they raise ``NotImplementedError``.
    """
    if not getattr(tracing_settings, "enabled", False):
        return NullSink()

    children: list[Any] = []
    for entry in tracing_settings.sinks:
        sink_type = getattr(entry, "type", None)
        if sink_type == "jsonl_file":
            raw_path = getattr(entry, "path", None) or _DEFAULT_LOCAL_TRACES_PATH
            children.append(JSONLFileSink(Path(raw_path)))
            continue
        if sink_type == "memory":
            children.append(MemorySink())
            continue
        if sink_type in {"logfire", "otel"}:
            msg = (
                f"{sink_type} sink is provided by the [tracing] extra (W8); "
                "install merge-craft[tracing] to enable it"
            )
            raise NotImplementedError(msg)
        msg = f"unknown tracing sink type: {sink_type!r}"
        raise ValueError(msg)

    if not children:
        return NullSink()
    return RedactingSink(MultiSink(children))


def read_jsonl_events(path: Path) -> Iterator[dict[str, Any]]:
    """Yield parsed JSON objects from a JSONL file, skipping malformed lines."""
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


__all__ = [
    "JSONLFileSink",
    "MemorySink",
    "MultiSink",
    "NullSink",
    "RedactingSink",
    "read_jsonl_events",
    "sink_factory",
]
