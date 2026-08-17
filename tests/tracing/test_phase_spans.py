"""Review-phase spans — OB4.1 RED suite (part 1 of 5).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB4,
sub-wave OB4.1, finding O9). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB4.2 phase emitter in ``mergecraft.tracing.signals`` (new):
``emit_phase(tracer, phase=...)`` opens, decorates and immediately closes a
``mergecraft.phase`` point span (the ``_tool_attrs.emit_verb_subevent``
discipline) carrying ``mergecraft.phase.name``. The phase vocabulary is the
EXISTING ``mcp/verdict.py::ReviewPhase`` enum (VP4) — OB4.2 must reuse it, not
declare a second one.

``test_a_run_that_never_submits_shows_the_missing_phase`` pins the diagnostic
value: a run that dies before SUBMIT leaves a trace whose phase list visibly
stops — the fail-closed case is diagnosable at a glance.

The ``signals`` import is lazy (shared fixture in ``tests/tracing/conftest.py``)
so collection stays clean; both tests carry non-strict ``xfail`` markers
(``green after OB4.2``) and are expected RED until OB4.2 lands.

Acceptance (plan §OB4.1, shared with the sibling modules): 14 collected;
0 pass; 14 RED (xfail).
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.mcp.verdict import ReviewPhase


@pytest.fixture
def tracer_and_sink() -> dict[str, Any]:
    """A real ``MemorySink`` wired to a ``Tracer`` with explicit correlation ids."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(
        sink=sink,
        session_id="session-ob4",
        run_id="run-ob4",
        trace_id="trace-ob4",
    )
    return {"sink": sink, "tracer": tracer}


@pytest.mark.xfail(reason="green after OB4.2: emit_phase", strict=False)
def test_each_review_phase_emits_a_span(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """O9 — every phase of the review lifecycle is visible as its own span."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    for phase in ReviewPhase:
        signals.emit_phase(tracer, phase=phase)

    events = sink.events
    assert len(events) == len(list(ReviewPhase))
    for event, phase in zip(events, ReviewPhase, strict=True):
        assert event.kind == "mergecraft.phase"
        assert event.attrs["mergecraft.phase.name"] == phase.value
    # Convention 3 — total and non-throwing: the disabled path is a no-op.
    from mergecraft.tracing import NullTracer

    signals.emit_phase(NullTracer(), phase=ReviewPhase.INIT)


@pytest.mark.xfail(reason="green after OB4.2: emit_phase", strict=False)
def test_a_run_that_never_submits_shows_the_missing_phase(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """A run that dies before SUBMIT leaves a trace that visibly stops early.

    Only the reached phases appear; the terminal phases are absent, so the
    fail-closed case (file 1's no-submission path) is diagnosable at a glance.
    """
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    reached = (
        ReviewPhase.INIT,
        ReviewPhase.ESTABLISH_SCOPE,
        ReviewPhase.COLLECT_EVIDENCE,
        ReviewPhase.REVIEW,
        ReviewPhase.NORMALIZE,
    )
    for phase in reached:
        signals.emit_phase(tracer, phase=phase)

    names = [event.attrs["mergecraft.phase.name"] for event in sink.events]
    assert names == [phase.value for phase in reached]
    assert ReviewPhase.SUBMIT.value not in names
    assert ReviewPhase.PUBLISH.value not in names
    assert ReviewPhase.COMPLETE.value not in names
