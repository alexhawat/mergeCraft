"""ProviderLLMPair helper regression tests (W6 / L-1).

The ``_open_provider_llm_pair`` helper (``src/mergecraft/tracing/tracer.py``)
opens a ``provider.call`` parent and an ``llm.call`` child in a single
atomic step. The public ``provider_llm_pair`` context manager wraps it
with a ``try/finally`` so an exception in the body still closes the
pair — but the streaming driver event handlers (``agents/claude.py``,
``agents/codex.py``, ``agents/gemini.py``) call ``_open_provider_llm_pair``
directly and store the pair in their own bookkeeping dict. If the
inner ``tracer.start_span(...)`` or ``llm_span.__enter__()`` raised
before the helper's try/except landed, the provider span was the
active frame on ``_ACTIVE_SPAN`` and would leak into the next call's
parent chain.

W6 / L-1 — the helper now wraps the post-``__enter__`` body in
``try/except`` that closes the provider span and re-raises. This test
simulates a ``start_span`` failure and asserts:

1. The exception propagates to the caller.
2. ``_ACTIVE_SPAN.get()`` is reset to ``None`` after the failure —
   the provider span's context-token frame is popped.
3. The provider span is still emitted via its own ``close()`` (so the
   half-open pair is visible in the sink).
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.tracing import tracer as tracer_mod


@pytest.fixture
def tracer_and_sink() -> Any:
    """A real ``MemorySink`` wired to a ``Tracer`` for span capture."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="l1-leak", run_id="l1-leak-run")
    return {"sink": sink, "tracer": tracer}


def test_provider_span_leak_reset_when_inner_start_span_fails(
    tracer_and_sink: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """W6 / L-1 — inner ``start_span`` failure resets the active-span frame.

    Forces ``Tracer.start_span`` to raise on the second call (the
    ``llm.call`` child) and asserts:

    - the original exception propagates to the caller,
    - ``_ACTIVE_SPAN.get()`` is reset to ``None`` after the failure
      (the provider span's context-token frame is popped, so the next
      ``tracer.start_span`` call does not chain a child onto the
      half-open provider span),
    - the provider span was emitted via its own ``close()`` (so the
      half-open pair is visible in the sink).
    """
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    # The helper calls ``tracer.start_span`` twice — once for the
    # ``provider.call`` parent, once for the ``llm.call`` child. The
    # second call is the one that should raise to exercise the L-1
    # leak path. We patch ``Tracer.start_span`` at the class level
    # (the tracer is a ``@dataclass(slots=True)`` so the instance is
    # read-only) and gate the failure on the second invocation's
    # ``kind``. Bind the original method to a local before patching
    # so the patched version can still delegate.
    original_start_span = tracer_mod.Tracer.start_span
    call_log: list[str] = []

    def flaky_start_span(self: Any, kind: str, *args: Any, **kwargs: Any) -> Any:
        call_log.append(kind)
        if kind == "llm.call":
            raise RuntimeError("simulated llm.call start_span failure")
        return original_start_span(self, kind, *args, **kwargs)

    monkeypatch.setattr(tracer_mod.Tracer, "start_span", flaky_start_span)

    # Confirm the active-span ContextVar starts empty.
    assert tracer_mod._ACTIVE_SPAN.get() is None, (
        "_ACTIVE_SPAN must be None before the helper runs "
        "(other test leakage would mask the L-1 bug)"
    )

    with pytest.raises(RuntimeError, match=r"simulated llm.call start_span failure"):
        tracer_mod._open_provider_llm_pair(
            tracer,
            model_id="anthropic/claude-sonnet",
            family="anthropic",
            provider_id="anthropic",
        )

    # The fix: the provider span's ``__exit__`` ran in the helper's
    # ``except`` branch, which popped the active-span frame. The
    # ContextVar must be reset to ``None`` — otherwise the next
    # ``tracer.start_span`` would treat the half-open provider span as
    # its parent.
    assert tracer_mod._ACTIVE_SPAN.get() is None, (
        "W6 / L-1 leak: _ACTIVE_SPAN still references the half-open "
        "provider span after a start_span failure"
    )

    # The provider span was closed by the helper's ``__exit__`` call,
    # so it must show up in the sink exactly once. The half-open
    # pair is visible to Logfire rather than silently lost.
    assert len(sink.events) == 1, (
        f"expected exactly one TraceEvent (the closed provider span), got {len(sink.events)}"
    )
    assert sink.events[0].kind == "provider.call", (
        f"unexpected span kind emitted: {sink.events[0].kind!r}"
    )
    # Sanity: the helper made the expected two start_span calls before
    # the second one raised.
    assert call_log == ["provider.call", "llm.call"], (
        f"helper should have called start_span twice (provider.call, llm.call), got {call_log!r}"
    )
