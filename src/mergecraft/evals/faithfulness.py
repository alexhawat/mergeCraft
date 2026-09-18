"""Logfire alerts on J4 parallel-judge faithfulness signals (E-D9).

Collects unverified-finding rate, evidence-pack ``contradicts`` rate, and
quote-verification failures from plan 23 J4's ``ParallelJudgeResult``.
``says_nothing`` is a quote-verification failure. This module does not
call Jev and does not replace the verifier.

Exports:
    FAITHFULNESS_SIGNAL_NAMES: Locked #723 item 5 signal names.
    FaithfulnessSignals: Rates and quote-failure count from one judge pack.
    collect_faithfulness_signals: Pure collector over ``ParallelJudgeResult``.
    emit_faithfulness_alerts: Write a ``mergecraft.faithfulness`` span.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from pydantic import BaseModel, ConfigDict

from mergecraft.jev.judge import ParallelJudgeResult

if TYPE_CHECKING:
    from mergecraft.tracing import Tracer

FAITHFULNESS_SIGNAL_NAMES: Final[tuple[str, ...]] = (
    "unverified_finding_rate",
    "contradicts_rate",
    "quote_verification_failures",
)

_QUOTE_FAILURE_RELATIONS: Final[frozenset[str]] = frozenset({"says_nothing", "contradicts"})


class FaithfulnessSignals(BaseModel):
    """The three #723 item 5 faithfulness signals. Zero is real data."""

    model_config = ConfigDict(extra="forbid")

    unverified_finding_rate: float
    contradicts_rate: float
    quote_verification_failures: int


def collect_faithfulness_signals(
    result: object,
    *,
    findings_total: int,
) -> FaithfulnessSignals:
    """Derive faithfulness rates from J4 output. No client, no second judge.

    Args:
        result: A ``ParallelJudgeResult`` from ``run_parallel_judge``.
        findings_total: Review findings the judge was asked about.

    Returns:
        FaithfulnessSignals: Honest zeros when the pack is empty (never NaN).

    Raises:
        TypeError: ``result`` is not a ``ParallelJudgeResult``.
    """
    if not isinstance(result, ParallelJudgeResult):
        msg = "collect_faithfulness_signals requires a ParallelJudgeResult"
        raise TypeError(msg)

    evidence = result.evidence
    evidence_count = len(evidence)
    contradicts = sum(1 for row in evidence if row.relation == "contradicts")
    quote_failures = sum(1 for row in evidence if row.relation in _QUOTE_FAILURE_RELATIONS)
    contradicts_rate = (contradicts / evidence_count) if evidence_count else 0.0
    unverified_rate = (quote_failures / findings_total) if findings_total else 0.0
    return FaithfulnessSignals(
        unverified_finding_rate=unverified_rate,
        contradicts_rate=contradicts_rate,
        quote_verification_failures=quote_failures,
    )


def emit_faithfulness_alerts(
    signals: FaithfulnessSignals,
    *,
    tracer: Tracer | None = None,
) -> None:
    """Write the three faithfulness attrs onto a ``mergecraft.faithfulness`` span.

    ``tracer=None`` is a total no-op — tracing must not fail a review.

    Args:
        signals: Collected rates and quote-failure count.
        tracer: Live tracer, or ``None`` to skip emit.
    """
    if tracer is None:
        return
    with tracer.start_span("mergecraft.faithfulness") as span:
        span.set_attribute(
            "mergecraft.faithfulness.unverified_finding_rate",
            signals.unverified_finding_rate,
        )
        span.set_attribute(
            "mergecraft.faithfulness.contradicts_rate",
            signals.contradicts_rate,
        )
        span.set_attribute(
            "mergecraft.faithfulness.quote_verification_failures",
            signals.quote_verification_failures,
        )


__all__ = [
    "FAITHFULNESS_SIGNAL_NAMES",
    "FaithfulnessSignals",
    "collect_faithfulness_signals",
    "emit_faithfulness_alerts",
]
