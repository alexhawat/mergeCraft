"""Direct unit tests for ``mergecraft.tracing.tracer`` (G5.1 / G-F10).

``tests/tracing/`` had 11 test modules exercising ``Tracer`` / ``Span`` only
transitively (through the instrumentation, streaming, and exporter suites);
none named ``test_tracer.py`` targeted the module's own public API directly.
This file closes that gap.

Five of the seven tests here characterise **existing** lifecycle behaviour
(propagation, nesting, idempotent close, the ``_ACTIVE_SPAN`` exception-safety
class, and the ``NullTracer`` no-op contract — #56 D9) and are green today.
The remaining two pin the **not-yet-implemented** span-count cap (G-F10: no
span-count cap exists, so a runaway review can emit an unbounded span tree)
and are marked ``xfail(strict=False)`` pending G5.2, which adds
``MAX_SPANS_PER_RUN`` to ``tracer.py``. Non-strict so G5.2 landing (an
``XPASS``) does not fail the suite — the reconciliation pass removes the
markers once G5.2 is green.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def tracer_and_sink() -> dict[str, Any]:
    """A real ``MemorySink`` wired to a ``Tracer`` with explicit correlation ids.

    ``session_id`` / ``trace_id`` are set explicitly (not left to resolve from
    the environment) so propagation assertions pin a real, non-default value
    rather than an accidental match against empty-string defaults.
    """
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session-abc",
        run_id="run-abc",
        trace_id="trace-abc",
    )
    return {"sink": sink, "tracer": tracer}


def test_start_span_propagates_session_and_trace_id(tracer_and_sink: dict[str, Any]) -> None:
    """A nested (child) span carries the tracer's ``session_id`` and ``trace_id``.

    Both ids are stamped from the owning ``Tracer`` at ``start_span`` time
    (``tracer.py:104-114``); this pins that a *child* span opened while a
    parent is active gets the same ids as the root, not a blank/derived pair.
    """
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with tracer.start_span("mergecraft.run") as parent, tracer.start_span("agent.attempt"):
        pass

    events = {event.kind: event for event in sink.events}
    child_event = events["agent.attempt"]
    assert child_event.session_id == tracer.session_id == "session-abc"
    assert child_event.trace_id == tracer.trace_id == "trace-abc"
    assert child_event.parent_span_id == parent.span_id


def test_nested_spans_form_a_parent_chain(tracer_and_sink: dict[str, Any]) -> None:
    """Three nested spans each record the immediately enclosing span as parent."""
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with (
        tracer.start_span("mergecraft.run") as level1,
        tracer.start_span("agent.attempt") as level2,
        tracer.start_span("llm.call") as level3,
    ):
        pass

    events = {event.kind: event for event in sink.events}
    assert events["mergecraft.run"].parent_span_id is None
    assert events["agent.attempt"].parent_span_id == level1.span_id
    assert events["llm.call"].parent_span_id == level2.span_id
    # Three genuinely distinct spans — no id reused across levels.
    assert len({level1.span_id, level2.span_id, level3.span_id}) == 3


def test_span_close_is_idempotent(tracer_and_sink: dict[str, Any]) -> None:
    """A second ``close()`` after a ``with``-block exit is a defensive no-op.

    Extends the W6 ``_closed`` coverage in ``tests/tracing/test_span_lifecycle.py``,
    which pins the *manually-built* span path (``start_span`` without
    ``__enter__``) and says explicitly "the ``with`` block path ... is
    unchanged here". This test exercises that other path: the context
    manager's ``__exit__`` performs the first (real) close, and a caller
    that also holds a reference to the span and calls ``close()`` again
    afterward must not emit a duplicate event, re-stamp ``ts_end_ns``, or
    re-set the active-span ContextVar.
    """
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with tracer.start_span("mergecraft.run") as span:
        pass

    assert len(sink.events) == 1
    frozen_end_ns = sink.events[0].ts_end_ns
    assert tracer.current_span() is None

    span.close()  # second close, post-exit — must be a silent no-op

    assert len(sink.events) == 1, "a second close() must not emit a duplicate TraceEvent"
    assert sink.events[0].ts_end_ns == frozen_end_ns, "a second close() must not restamp ts_end_ns"
    assert tracer.current_span() is None


def test_active_span_contextvar_restores_on_exception(tracer_and_sink: dict[str, Any]) -> None:
    """A raising span body still pops the ``_ACTIVE_SPAN`` frame (the W5 leak class).

    ``Span.__exit__`` records the exception and calls ``close()`` even when
    the body raised, resetting the ``_ACTIVE_SPAN`` ContextVar token. Without
    that, the aborted span would stay "active" and the next ``start_span``
    call would silently chain a new span onto a dead parent.
    """
    from mergecraft.tracing import tracer as tracer_mod

    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    assert tracer_mod._ACTIVE_SPAN.get() is None

    caught: RuntimeError | None = None
    try:
        with tracer.start_span("mergecraft.run"):
            assert tracer.current_span() is not None
            raise RuntimeError("boom")
    except RuntimeError as exc:
        caught = exc

    assert caught is not None, "the body's exception must still propagate past Span.__exit__"
    assert str(caught) == "boom"

    # The frame popped even though the body raised.
    assert tracer_mod._ACTIVE_SPAN.get() is None
    assert tracer.current_span() is None

    # The aborted span was still emitted, marked failed.
    assert len(sink.events) == 1
    aborted_event = sink.events[0]
    assert aborted_event.status == "error"
    assert aborted_event.attrs.get("error") == "boom"

    # A span opened afterward is a fresh root — not chained onto the dead frame.
    with tracer.start_span("mergecraft.run") as next_span:
        assert next_span.parent_span_id is None


def test_null_tracer_is_a_true_noop() -> None:
    """``NullTracer.start_span`` never evaluates ``attrs_source`` (#56 D9).

    A disabled tracer must cost nothing on the hot path: no span object
    bookkeeping and, critically, no invocation of the (possibly expensive)
    lazy ``attrs_source`` callable. This is the standing decision the cap
    (G5.2) must also respect for ``NullTracer`` — the cap only ever applies
    to the real ``Tracer``.
    """
    from mergecraft.tracing import NullTracer

    tracer = NullTracer()
    assert tracer.current_span() is None

    attrs_calls = 0

    def attrs_source() -> dict[str, Any]:
        nonlocal attrs_calls
        attrs_calls += 1
        return {"should": "never-build"}

    with tracer.start_span("mergecraft.run", attrs_source=attrs_source) as span:
        span.set_attribute("model.id", "anthropic/claude-sonnet")
        span.record_exception(RuntimeError("ignored"))
        span.set_status("error", "ignored")

    assert attrs_calls == 0, "NullTracer must never evaluate attrs_source"
    assert tracer.current_span() is None


@pytest.mark.xfail(reason="green after G5.2: span-count cap", strict=False)
def test_span_count_cap_stops_emission_at_limit() -> None:
    """Opening more than the cap stops emission at exactly ``MAX_SPANS_PER_RUN``.

    G-F10 / #56 — nothing today bounds span growth, so a large review (or a
    genuine runaway) can emit an unbounded span tree. G5.2 adds
    ``MAX_SPANS_PER_RUN`` and a ``_span_count`` counter on ``Tracer``; past
    the cap, ``start_span`` returns a ``NullSpan`` instead of a real ``Span``
    so the configured sink never receives more than the cap's worth of
    events. ``MAX_SPANS_PER_RUN`` does not exist yet — the import below is
    the RED assertion.
    """
    from mergecraft.tracing import MemorySink, Tracer
    from mergecraft.tracing.tracer import MAX_SPANS_PER_RUN

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="cap-session", run_id="cap-run")
    for _ in range(MAX_SPANS_PER_RUN + 10):
        with tracer.start_span("mergecraft.run"):
            pass

    assert len(sink.events) == MAX_SPANS_PER_RUN


@pytest.mark.xfail(reason="green after G5.2: span-count cap", strict=False)
def test_span_cap_logs_once_and_does_not_raise() -> None:
    """Hitting the span cap logs exactly one warning and never raises (#56 D6).

    Tracing is best-effort everywhere else in this module (sink write
    failures, ``attrs_source`` failures both degrade to a ``logger.warning``
    and continue); the cap must honor the same contract. A runaway span tree
    degrades to silence past the limit, not an exception that could abort
    the review the tracer is merely observing.
    """
    import loguru

    from mergecraft.tracing import MemorySink, Tracer
    from mergecraft.tracing.tracer import MAX_SPANS_PER_RUN

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="cap-session", run_id="cap-run")
    captured: list[str] = []
    sink_id = loguru.logger.add(
        lambda record: captured.append(record.record["message"]), level="WARNING"
    )
    try:
        for _ in range(MAX_SPANS_PER_RUN + 10):
            with tracer.start_span("mergecraft.run"):
                pass
    finally:
        loguru.logger.remove(sink_id)

    assert len(captured) == 1, f"expected exactly one cap warning, got {captured!r}"


__all__ = [
    "test_active_span_contextvar_restores_on_exception",
    "test_nested_spans_form_a_parent_chain",
    "test_null_tracer_is_a_true_noop",
    "test_span_cap_logs_once_and_does_not_raise",
    "test_span_close_is_idempotent",
    "test_span_count_cap_stops_emission_at_limit",
    "test_start_span_propagates_session_and_trace_id",
]
