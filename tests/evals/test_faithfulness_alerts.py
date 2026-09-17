"""E4 — Logfire alerts on J4 faithfulness signals, no second judge (E-D9).

Closes #723 item 5. Signals come from plan 23 J4's ``ParallelJudgeResult`` /
evidence pack: unverified-finding rate, ``contradicts`` rate, and
quote-verification failures (``jev-evidence-unsupported``).
"""

from __future__ import annotations

from typing import Any

import pytest
from tests.evals.support_eval_calibration import FAITHFULNESS_SIGNAL_NAMES

from mergecraft.analyzers.finding import make_finding
from mergecraft.jev.judge import (
    EvidenceJudgeResult,
    ParallelJudgeResult,
)

E4_XFAIL = pytest.mark.xfail(
    reason="green after E4: Logfire alerts on J4 faithfulness signals",
    strict=False,
)


def _faith() -> Any:
    import mergecraft.evals.faithfulness as module

    return module


def _unsupported(*, relation: str) -> EvidenceJudgeResult:
    finding = make_finding(
        tool="jev-judge",
        rule_id="jev-evidence-unsupported",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message=f"Finding is not supported by the cited code (relation={relation})",
        path="src/example.py",
        start_line=1,
        end_line=1,
        source="agent",
        evidence=["quoted snippet"],
        scope="run",
    )
    return EvidenceJudgeResult(
        relation=relation,
        scope="run",
        blocking=False,
        findings=[finding],
    )


def _supported() -> EvidenceJudgeResult:
    return EvidenceJudgeResult(relation="supports", scope="run", blocking=False, findings=[])


@E4_XFAIL
def test_collect_faithfulness_signals_from_parallel_judge() -> None:
    """Happy: rates and quote failures are derived from J4 output, not a new judge."""
    module = _faith()
    result = ParallelJudgeResult(
        replaces_verifier=False,
        evidence=[_unsupported(relation="contradicts"), _supported()],
        findings=_unsupported(relation="contradicts").findings,
    )
    signals = module.collect_faithfulness_signals(result, findings_total=2)
    assert signals.contradicts_rate == pytest.approx(0.5)
    assert signals.quote_verification_failures == 1
    assert signals.unverified_finding_rate == pytest.approx(0.5)
    for name in FAITHFULNESS_SIGNAL_NAMES:
        assert hasattr(signals, name)


@E4_XFAIL
def test_empty_judge_result_is_honest_zero() -> None:
    """Edge: no evidence yields 0.0 rates, never NaN."""
    module = _faith()
    signals = module.collect_faithfulness_signals(
        ParallelJudgeResult(replaces_verifier=False),
        findings_total=0,
    )
    assert signals.unverified_finding_rate == 0.0
    assert signals.contradicts_rate == 0.0
    assert signals.quote_verification_failures == 0


@E4_XFAIL
def test_says_nothing_is_a_quote_verification_failure() -> None:
    """Quote-verification failures include ``says_nothing`` evidence rows."""
    module = _faith()
    result = ParallelJudgeResult(
        replaces_verifier=False,
        evidence=[_unsupported(relation="says_nothing")],
        findings=_unsupported(relation="says_nothing").findings,
    )
    signals = module.collect_faithfulness_signals(result, findings_total=1)
    assert signals.quote_verification_failures == 1
    assert signals.contradicts_rate == 0.0
    assert signals.unverified_finding_rate == pytest.approx(1.0)


@E4_XFAIL
def test_collect_does_not_require_a_client() -> None:
    """No second judge: collection is a pure function of ``ParallelJudgeResult``."""
    module = _faith()
    signals = module.collect_faithfulness_signals(
        ParallelJudgeResult(replaces_verifier=False, evidence=[_supported()]),
        findings_total=1,
    )
    assert signals.quote_verification_failures == 0
    assert not hasattr(module, "AsyncJevClient")
    assert getattr(module, "replaces_verifier", False) is False


@E4_XFAIL
def test_emit_faithfulness_alerts_writes_all_three_signals() -> None:
    """Logfire-hookable span attrs for the three #723 item 5 signals, zeros included."""
    from mergecraft.tracing import MemorySink, Tracer

    module = _faith()
    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="s", run_id="r", trace_id="t")
    signals = module.FaithfulnessSignals(
        unverified_finding_rate=0.0,
        contradicts_rate=0.25,
        quote_verification_failures=2,
    )
    module.emit_faithfulness_alerts(signals, tracer=tracer)
    events = [event for event in sink.events if "faithfulness" in event.kind]
    assert events, "expected a mergecraft.faithfulness span"
    attrs = events[0].attrs
    assert attrs["mergecraft.faithfulness.unverified_finding_rate"] == 0.0
    assert attrs["mergecraft.faithfulness.contradicts_rate"] == 0.25
    assert attrs["mergecraft.faithfulness.quote_verification_failures"] == 2


@E4_XFAIL
def test_emit_faithfulness_alerts_null_tracer_is_a_noop() -> None:
    """Tracing must not fail a review — ``None`` tracer is total."""
    module = _faith()
    signals = module.FaithfulnessSignals(
        unverified_finding_rate=1.0,
        contradicts_rate=1.0,
        quote_verification_failures=3,
    )
    module.emit_faithfulness_alerts(signals, tracer=None)


@E4_XFAIL
def test_faithfulness_signal_names_match_the_locked_set() -> None:
    """Named deliverable: the three signals #723 item 5 lists, no extras as aliases."""
    module = _faith()
    names = tuple(module.FAITHFULNESS_SIGNAL_NAMES)
    assert names == FAITHFULNESS_SIGNAL_NAMES


@E4_XFAIL
def test_collect_rejects_a_non_judge_result() -> None:
    """Error: a random object is not silently treated as an empty pack."""
    module = _faith()
    with pytest.raises((TypeError, ValueError)):
        module.collect_faithfulness_signals("not-a-judge-result", findings_total=1)
