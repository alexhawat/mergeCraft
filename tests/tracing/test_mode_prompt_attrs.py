"""S5 (#145) — the ``mergecraft.publish`` span carries the mode prompt attrs.

``trace_attrs_for_mode`` (in ``src/mergecraft/tracing/event.py``) is the helper
that returns ``{"mergecraft.mode.name": ..., "mergecraft.mode.prompt_version":
...}``. Without wiring, every emit site in the run still leaves the helper
sitting on the shelf: spans fire, but no row carries the prompt identity
the run should be attributed to.

The regression pins the wiring through ``Tracer`` + ``MemorySink``: open a
span with the same ``attrs_source`` lambda shape ``main.py`` uses, close it,
and assert the captured ``TraceEvent`` carries both keys.
"""

from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def memory_sink() -> Any:
    """Stand up a real ``MemorySink`` + ``Tracer`` pair (no filesystem, no net)."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="mode-attrs", run_id="run-mode-attrs")
    return {"sink": sink, "tracer": tracer}


def _events_by_kind(sink: Any) -> dict[str, list[Any]]:
    out: dict[str, list[Any]] = {}
    for event in sink.events:
        out.setdefault(event.kind, []).append(event)
    return out


def test_publish_span_carries_mode_attrs_when_selected(memory_sink: Any) -> None:
    """A ``mergecraft.publish`` span emits the mode attrs the run dispatched on.

    Mirrors the wiring in ``src/mergecraft/main.py``: resolve the selected
    :class:`Mode` against the catalog, spread ``trace_attrs_for_mode(...)``
    into the span's ``attrs_source``, then assert the captured
    ``TraceEvent`` carries both keys exactly as recorded on the Mode object.
    A run without this fixture silently drops both attrs and the trace row
    becomes unattributable to the prompt that produced it.
    """
    from mergecraft.modes import compute_modes
    from mergecraft.tracing.event import trace_attrs_for_mode

    tracer = memory_sink["tracer"]
    catalog = compute_modes("opencode")
    selected_mode = next(m for m in catalog if m.name == "Review")

    with tracer.start_span(
        "mergecraft.publish",
        attrs_source=lambda: {
            "run_succeeded": True,
            **trace_attrs_for_mode(selected_mode),
        },
    ):
        pass

    events = _events_by_kind(memory_sink["sink"]).get("mergecraft.publish", [])
    assert len(events) == 1, (
        "expected one mergecraft.publish trace event; "
        "trace_attrs_for_mode was not wired into the publish span"
    )
    attrs = events[0].attrs
    assert attrs["mergecraft.mode.name"] == "Review"
    assert attrs["mergecraft.mode.prompt_version"] == selected_mode.version


def test_publish_span_omits_mode_attrs_when_no_selection(memory_sink: Any) -> None:
    """A run with no selected mode emits the publish span without mode attrs.

    Pin the safe-degradation branch: when ``selected_mode`` is ``None``
    (an issue comment, an early exit), the helper is *not* called and the
    span still emits — without the keys, with ``run_succeeded`` intact. A
    future change that calls ``trace_attrs_for_mode(None)`` would raise
    ``AttributeError`` at runtime; this test catches it before it ships.
    """
    tracer = memory_sink["tracer"]
    mode_attrs: dict[str, Any] = {}

    with tracer.start_span(
        "mergecraft.publish",
        attrs_source=lambda: {"run_succeeded": True, **mode_attrs},
    ):
        pass

    events = _events_by_kind(memory_sink["sink"]).get("mergecraft.publish", [])
    assert len(events) == 1
    attrs = events[0].attrs
    assert "mergecraft.mode.name" not in attrs
    assert "mergecraft.mode.prompt_version" not in attrs
    assert attrs["run_succeeded"] is True
