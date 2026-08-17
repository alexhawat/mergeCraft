"""Eval score spans — OB4.1 RED suite (part 5 of 5).

Wave plan: ``.ignorelocal/waves/04-observability-eval-wave-plan.md`` (PR OB4,
sub-wave OB4.1, finding O9). Test-plan doc: ``docs/test-plans/04-observability-eval.md``.

Pins the OB4.2 point-span emitter ``emit_eval_score`` in
``mergecraft.tracing.signals`` (new), emitted from the ``evals/`` scoring path:
one ``mergecraft.eval.score`` span per scored case, each metric as its own
``mergecraft.eval.<metric>`` attribute, keyed by ``mergecraft.eval.case_id``.

**D12**: eval scores are spans AND files — the span inherits the active
``review.id`` (via the OB1 D4 close-time merge), which is what makes the
eval↔trace join free rather than separately built.

Convention 5 (``test_span_cap_not_approached_by_a_normal_review``): a normal
review's signal spans are O(dozens) — three orders of magnitude under
``MAX_SPANS_PER_RUN`` (10 000). New span kinds must not change that.

The ``signals`` import is lazy (shared fixture in ``tests/tracing/conftest.py``),
which kept collection clean at RED-suite time; all three tests carried
non-strict ``xfail`` markers (``green after OB4.2``) until the post-OB4.2
reconciliation removed them (commit ``a3e9302`` made them XPASS), so all three
are now clean real passes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable


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


def test_eval_score_emits_each_metric_as_an_attribute(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """O9 — every scored metric lands as its own queryable attribute."""
    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    signals.emit_eval_score(
        tracer,
        case_id="case-001",
        metrics={
            "recall": 0.75,
            "corpus_confirmed_precision": 0.9,
            "duplicate_rate": 0.0,
        },
    )

    event = sink.events[0]
    assert event.kind == "mergecraft.eval.score"
    assert event.attrs["mergecraft.eval.case_id"] == "case-001"
    assert event.attrs["mergecraft.eval.recall"] == 0.75
    assert event.attrs["mergecraft.eval.corpus_confirmed_precision"] == 0.9
    assert event.attrs["mergecraft.eval.duplicate_rate"] == 0.0, "a zero metric is real data"


def test_eval_span_inherits_the_review_id(
    tracer_and_sink: dict[str, Any],
    signals_module: Any,
    review_context_module: Any,
    review_context_factory: Callable[..., Any],
) -> None:
    """D12 — the eval span inherits the active ``review.id``: the eval↔trace join is free."""
    signals = signals_module
    rc = review_context_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    with rc.bind_review_context(review_context_factory(review_id="review-ob4-eval")):
        signals.emit_eval_score(tracer, case_id="case-001", metrics={"recall": 1.0})

    event = sink.events[0]
    assert event.kind == "mergecraft.eval.score"
    assert event.attrs["review.id"] == "review-ob4-eval"
    assert event.attrs["review.correlation_key"], "the correlation key rides along too"


def test_span_cap_not_approached_by_a_normal_review(
    tracer_and_sink: dict[str, Any], signals_module: Any
) -> None:
    """Convention 5 — a normal review's signal spans are O(dozens), nowhere near the cap."""
    from mergecraft.mcp.verdict import ReviewPhase
    from mergecraft.tracing.content import ContentCapture
    from mergecraft.tracing.tracer import MAX_SPANS_PER_RUN

    signals = signals_module
    tracer = tracer_and_sink["tracer"]
    sink = tracer_and_sink["sink"]

    # A realistic normal review: every lifecycle phase, three agents with a
    # couple of tool calls each, five findings through a three-stage
    # lifecycle, one verdict, two eval scores.
    for phase in ReviewPhase:
        signals.emit_phase(tracer, phase=phase)
    for agent_id in ("orchestrator-1", "reviewer-1", "verifier-1"):
        with signals.agent_run_span(tracer, agent_id=agent_id, role=agent_id.split("-")[0]):
            for _ in range(2):
                with tracer.start_span("tool.call"):
                    pass
    for index in range(5):
        for stage in ("proposed", "verified", "published"):
            signals.emit_finding(
                tracer,
                fingerprint=f"fp-{index}",
                stage=stage,
                policy=ContentCapture.METADATA,
            )
    signals.emit_verdict(tracer, agent_verdict="approve", structural_verdict="pass")
    for case_id in ("case-001", "case-002"):
        signals.emit_eval_score(tracer, case_id=case_id, metrics={"recall": 1.0})

    expected = 10 + 3 + 6 + 15 + 1 + 2
    assert len(sink.events) == expected == 37, (
        "every signal span of a normal review is emitted — nothing suppressed"
    )
    assert len(sink.events) < MAX_SPANS_PER_RUN // 100, (
        f"a normal review must stay two orders of magnitude under {MAX_SPANS_PER_RUN}"
    )
