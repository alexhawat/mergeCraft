"""Span lifecycle regression tests (W6 / L-2).

The ``Span._closed`` flag (``src/mergecraft/tracing/tracer.py``) and the
``if self._closed: return`` gate in ``Span.close()`` replace the prior
``_context_token is None`` gate. The previous gate conflated two distinct
states — a manually-built span that was never entered (``_context_token``
is ``None`` on the first ``close``) and a span that has already been
closed (a re-close of an idempotent path). Both cases silently dropped
the second emit; the W5 / L-2 fix unifies them under a dedicated
``_closed`` flag so manually-built spans emit exactly once and
re-closing is a defensive no-op.

These two tests pin the contract the W5 / L-2 fix shipped — the only
explicit coverage of the manually-built span path in
``tests/tracing/``. The ``with`` block path is exercised across the rest
of the tracing suite and is unchanged here.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def tracer_and_sink() -> Any:
    """A real ``MemorySink`` wired to a ``Tracer`` for span capture."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="span-lifecycle", run_id="lifecycle-run")
    return {"sink": sink, "tracer": tracer}


def test_span_close_emits_when_never_entered(tracer_and_sink: Any) -> None:
    """A span built via ``tracer.start_span(...)`` without ``__enter__`` emits once.

    W5 / L-2 — the prior ``_context_token is None`` gate dropped the emit
    for the manually-built case (the verb sub-event emission, the
    ``provider_llm_pair`` helper, the HTTP wrapper close sites all build
    spans this way). The dedicated ``_closed`` flag lets the first
    ``close()`` proceed; the second call (idempotency) is exercised by
    the next test.
    """
    sink = tracer_and_sink["sink"]
    tracer = tracer_and_sink["tracer"]

    span = tracer.start_span("verb.subevent")
    # No ``__enter__`` call — the span's ``_context_token`` stays ``None``
    # until ``close()`` runs. This is the manually-built path the W5
    # helper sites use.
    span.close()

    assert len(sink.events) == 1, (
        f"expected exactly one TraceEvent from a manually-built span, got {len(sink.events)}"
    )
    event = sink.events[0]
    assert event.kind == "verb.subevent"
    assert event.span_id == span.span_id
    assert event.ts_end_ns >= event.ts_start_ns, (
        f"close() must stamp ts_end_ns >= ts_start_ns "
        f"(start={event.ts_start_ns}, end={event.ts_end_ns})"
    )


def test_span_close_is_idempotent(tracer_and_sink: Any) -> None:
    """A second ``close()`` on the same span is a defensive no-op.

    W5 / L-2 — the LIFO close discipline in
    ``_close_provider_llm_pair`` calls ``close()`` once per span, but
    external code that wires a span into multiple lifecycle hooks
    (provider pair + driver terminal event) must be able to call
    ``close()`` twice without emitting a duplicate TraceEvent or
    raising. The first call emits; the second call returns silently.
    """
    sink = tracer_and_sink["sink"]
    tracer = tracer_and_sink["tracer"]

    span = tracer.start_span("verb.subevent")
    span.close()
    # Second close — must not raise and must not emit a duplicate.
    span.close()

    assert len(sink.events) == 1, (
        f"expected exactly one TraceEvent after two close() calls, got {len(sink.events)}"
    )
