"""Verdict span — OB4.1 RED suite (part 4 of 5).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB4,
sub-wave OB4.1, finding O9). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB4.2 point-span emitter ``emit_verdict`` in
``mergecraft.tracing.signals`` (new), emitted where the publish path already
converges (``main.py`` ``mergecraft.publish``). One ``mergecraft.verdict``
span carries:

- ``mergecraft.verdict.agent`` — the agent's terminal verdict
  (``approve`` / ``request_changes``, the existing ``mcp/verdict.py``
  vocabulary);
- ``mergecraft.verdict.structural`` — the structural/static-checks verdict
  (``pass`` / ``fail``);
- ``mergecraft.verdict.disagreement`` — DERIVED by the emitter (agent says
  approve while structure fails, or vice versa), never caller-supplied: the
  fastest way to catch a gate rubber-stamping;
- ``mergecraft.verdict.findings_published`` /
  ``mergecraft.verdict.findings_withdrawn`` counts and
  ``mergecraft.verdict.fallback_reason`` (omitted when no fallback occurred —
  absent, never null).

The ``signals`` import is lazy (shared fixture in ``tests/tracing/conftest.py``)
so collection stays clean; all three tests carry non-strict ``xfail`` markers
(``green after OB4.2``) and are expected RED until OB4.2 lands.
"""

from __future__ import annotations

from typing import Any

import pytest


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


@pytest.mark.xfail(reason="green after OB4.2: emit_verdict", strict=False)
def test_carries_agent_and_structural_verdict(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """O9 — one verdict span carries both the agent and the structural verdict."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    signals.emit_verdict(
        tracer,
        agent_verdict="request_changes",
        structural_verdict="pass",
        published_count=2,
        withdrawn_count=0,
    )

    event = sink.events[0]
    assert event.kind == "mergecraft.verdict"
    assert event.attrs["mergecraft.verdict.agent"] == "request_changes"
    assert event.attrs["mergecraft.verdict.structural"] == "pass"


@pytest.mark.xfail(reason="green after OB4.2: derived disagreement flag", strict=False)
def test_disagreement_flag_is_derived(tracer_and_sink: dict[str, Any], signals_module: Any) -> None:
    """The disagreement flag is computed by the emitter from the two verdicts.

    approve + fail (or request_changes + pass) is a disagreement; aligned
    pairs are not. The caller never supplies the flag — a rubber-stamping
    gate cannot hide the mismatch by omitting it.
    """
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    signals.emit_verdict(tracer, agent_verdict="approve", structural_verdict="fail")
    signals.emit_verdict(tracer, agent_verdict="request_changes", structural_verdict="pass")
    signals.emit_verdict(tracer, agent_verdict="approve", structural_verdict="pass")
    signals.emit_verdict(tracer, agent_verdict="request_changes", structural_verdict="fail")

    flags = [event.attrs["mergecraft.verdict.disagreement"] for event in sink.events]
    assert flags == [True, True, False, False]


@pytest.mark.xfail(reason="green after OB4.2: verdict counts + fallback reason", strict=False)
def test_counts_and_fallback_reason_recorded(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """Findings counts ride the verdict span; a fallback reason is recorded when set.

    ``fallback_reason`` is omitted entirely (not null) when no fallback
    occurred — a span that never fell back must not carry a misleading
    empty value.
    """
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    signals.emit_verdict(
        tracer,
        agent_verdict="approve",
        structural_verdict="pass",
        published_count=3,
        withdrawn_count=1,
        fallback_reason="model_unavailable",
    )
    signals.emit_verdict(
        tracer,
        agent_verdict="approve",
        structural_verdict="pass",
        published_count=1,
        withdrawn_count=0,
    )

    with_fallback, without_fallback = (event.attrs for event in sink.events)
    assert with_fallback["mergecraft.verdict.findings_published"] == 3
    assert with_fallback["mergecraft.verdict.findings_withdrawn"] == 1
    assert with_fallback["mergecraft.verdict.fallback_reason"] == "model_unavailable"
    assert without_fallback["mergecraft.verdict.findings_published"] == 1
    assert "mergecraft.verdict.fallback_reason" not in without_fallback
