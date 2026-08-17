"""EV3 — the release regression gate: material regression blocks, noise passes.

RED suite for PR EV3 (sub-wave EV3.1; implementation EV3.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

EV3 wires ``mergecraft eval gate`` into the release workflow as a blocker with
a **declared tolerance band** (plan §EV3.2): a candidate result set is compared
against the published baseline, a metric that regresses by more than the band
fails the release, and noise inside the band passes — otherwise the gate is
either decorative or flaky, and both are worse than no gate.

Pinned contract (all new in EV3.2, module ``mergecraft.evals.gate``):

- ``DEFAULT_GATE_TOLERANCE`` — the declared band (expected ``0.02``: wider than
  one-case noise on the current corpus, far narrower than any material
  multi-case regression). The tests below use it as the default invocation
  tolerance and pin only that it is smaller than a material regression.
- ``eval_gate(*, candidate: BenchmarkResultSet, baseline: BenchmarkResultSet,
  tolerance: float = DEFAULT_GATE_TOLERANCE) -> GateReport`` — pure comparison
  of the result sets' scalar gate metrics. Direction-aware: a *drop* in
  ``decision_replay_pass_rate`` regresses; a *rise* in
  ``unsafe_approval_rate`` / ``clean_block_rate`` regresses.
- ``GateReport`` — ``passed: bool``, ``tolerance: float``,
  ``deltas: list[MetricDelta]`` (``metric`` / ``baseline`` / ``candidate`` /
  ``delta`` / ``regressed`` per compared metric), and
  ``regressed_metrics: tuple[str, ...]`` naming every regressed metric — the
  release log must say *which* number moved, not just "failed".

Fixtures are real ``BenchmarkResultSet``\\ s from ``run_structural_replay`` on a
synthetic bank, with the two gated rates overridden via ``model_copy`` — the
gate contract is about the comparison, not about replay arithmetic. Keyless
and pure: ``skipped: no live gate``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mergecraft.evals.benchmark import BenchmarkResultSet, run_structural_replay
from mergecraft.evals.store import Case, add_case
from mergecraft.utils.learnings import LearningProvenance

_XFAIL_EV3_2 = pytest.mark.xfail(
    reason="green after EV3.2: mergecraft.evals.gate eval_gate + GateReport + tolerance band",
    strict=False,
)

_WHEN = datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)


# ── result-set fixtures (mirrors tests/evals/test_reproducibility.py) ──


def _provenance() -> LearningProvenance:
    return LearningProvenance(
        run_id="synthetic",
        pr_number=1,
        source_field="eval_bank",
        author_login="synthetic",
        author_association="OWNER",
        trust_tier="trusted",
        timestamp=_WHEN,
    )


def _bank_case(case_id: str) -> Case:
    """A trivially-replayable bank case — only the gate comparison is under test."""
    return Case(
        id=case_id,
        title=f"gate fixture {case_id}",
        category="missed_finding",
        submitted_at=_WHEN,
        run_id="synthetic",
        pr_number=1,
        failure_mode="wrong_decision",
        expected_finding="synthetic",
        expected_decision="neutral",
        replay_command=f"mergecraft eval replay {case_id}",
        provenance=_provenance(),
        body="",
        recorded_findings=[],
        run_succeeded=True,
        trust_tier="trusted",
    )


def _result_set(
    tmp_path: Path, *, pass_rate: float, unsafe_approval_rate: float
) -> BenchmarkResultSet:
    """A real result set with the two gated rates set to exact values."""
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))
    result = run_structural_replay(bank, providers=("claude",))
    metrics = result.metrics.model_copy(
        update={
            "decision_replay_pass_rate": pass_rate,
            "unsafe_approval_rate": unsafe_approval_rate,
        }
    )
    return result.model_copy(update={"metrics": metrics})


# ── the gate ──


@_XFAIL_EV3_2
def test_release_fails_on_a_material_regression(tmp_path: Path) -> None:
    """A 20-point pass-rate drop is material by any reasonable band — the
    gate fails, and the declared band is pinned smaller than that."""
    from mergecraft.evals.gate import DEFAULT_GATE_TOLERANCE, eval_gate

    baseline = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate = _result_set(tmp_path / "cand", pass_rate=0.70, unsafe_approval_rate=0.10)

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is False
    assert 0 < DEFAULT_GATE_TOLERANCE < 0.20


@_XFAIL_EV3_2
def test_release_gate_reports_which_metric_regressed(tmp_path: Path) -> None:
    """Only ``unsafe_approval_rate`` moved — the report names exactly that
    metric as regressed (direction-aware: a *rise* in an error rate is the
    regression) and does not smear the unchanged pass rate."""
    from mergecraft.evals.gate import eval_gate

    baseline = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate = _result_set(tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.30)

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is False
    assert "unsafe_approval_rate" in report.regressed_metrics
    assert "decision_replay_pass_rate" not in report.regressed_metrics


@_XFAIL_EV3_2
def test_gate_tolerates_noise_within_the_declared_band(tmp_path: Path) -> None:
    """One-point wobble on both gated rates, inside the declared default
    band: the gate passes and names no regressed metric — a gate that alarms
    on noise trains operators to ignore it."""
    from mergecraft.evals.gate import DEFAULT_GATE_TOLERANCE, eval_gate

    baseline = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate = _result_set(tmp_path / "cand", pass_rate=0.89, unsafe_approval_rate=0.11)

    report = eval_gate(candidate=candidate, baseline=baseline, tolerance=DEFAULT_GATE_TOLERANCE)

    assert report.passed is True
    assert report.regressed_metrics == ()
