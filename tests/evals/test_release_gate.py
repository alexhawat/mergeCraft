"""EV3 — the release regression gate: material regression blocks, noise passes.

Authored RED for PR EV3 (sub-wave EV3.1; implementation EV3.2 landed in
``0aff25c``; xfail markers reconciled post-EV3.2). Wave plan:
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

RED additions for the coverage wave (EV1, implementation EV2). Two failure
modes the gate used to ignore are now gated, both *lower is better*:

- structural ``inconclusive_rate`` — a crashed or non-replayable case leaves
  the unsafe-approval denominator, so the rate the gate watched could only
  improve; the inconclusive rate that records the missing evidence was
  computed on every result set and gated by nothing.
- detection ``failed_case_rate`` (``cases_failed / (cases_run + cases_failed)``,
  a computed property on ``DetectionMetrics``) — the empty detection fold
  reports recall/precision/F1 of ``1.0``, so an all-failed run read as perfect.

And one missing-half guard: with ``require_halves=True`` a candidate missing a
half the baseline carries fails and names the missing half; without the flag
the absent half is skipped as today (the PR check's candidate never carries
detection). These tests are RED today — ``inconclusive_rate`` is not compared,
``failed_case_rate`` does not exist, and ``eval_gate`` has no ``require_halves``
keyword — all at call time, never at collection.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from mergecraft.evals.benchmark import BenchmarkResultSet, run_structural_replay
from mergecraft.evals.live_run import DetectionMetrics
from mergecraft.evals.scoring import AggregateScoreReport
from mergecraft.evals.store import Case, add_case
from mergecraft.utils.learnings import LearningProvenance

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
    tmp_path: Path,
    *,
    pass_rate: float,
    unsafe_approval_rate: float,
    inconclusive_rate: float = 0.0,
) -> BenchmarkResultSet:
    """A real result set with the gated structural rates set to exact values."""
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))
    result = run_structural_replay(bank, providers=("claude",))
    metrics = result.metrics.model_copy(
        update={
            "decision_replay_pass_rate": pass_rate,
            "unsafe_approval_rate": unsafe_approval_rate,
            "inconclusive_rate": inconclusive_rate,
        }
    )
    return result.model_copy(update={"metrics": metrics})


def _aggregate(*, total_issues: int, total_reported: int, found: int) -> AggregateScoreReport:
    """A minimal detection aggregate with exact recall/precision inputs."""
    return AggregateScoreReport(
        total_cases=1,
        total_issues=total_issues,
        total_reported=total_reported,
        found=found,
        false_negatives=max(total_issues - found, 0),
        unadjudicated=0,
        false_positives=max(total_reported - found, 0),
        false_positives_per_case=0.0,
        clean_case_fp_rate=0.0,
    )


def _detection(
    *,
    cases_run: int,
    cases_failed: int,
    total_issues: int,
    total_reported: int,
    found: int,
) -> DetectionMetrics:
    """A detection half with an explicit attempted/succeeded/failed split."""
    return DetectionMetrics(
        provider="claude",
        model="claude-sonnet-5",
        cases_run=cases_run,
        cases_failed=cases_failed,
        failed_case_ids=[f"synthetic-failed-{index:03d}" for index in range(cases_failed)],
        aggregate=_aggregate(
            total_issues=total_issues,
            total_reported=total_reported,
            found=found,
        ),
        case_results=[],
        raw_findings_dir="",
    )


def _with_detection(
    result: BenchmarkResultSet, detection: DetectionMetrics | None
) -> BenchmarkResultSet:
    return result.model_copy(update={"detection": detection})


# ── the gate ──


def test_release_fails_on_a_material_regression(tmp_path: Path) -> None:
    """A 20-point pass-rate drop is material by any reasonable band — the
    gate fails, and the declared band is pinned smaller than that."""
    from mergecraft.evals.gate import DEFAULT_GATE_TOLERANCE, eval_gate

    baseline = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate = _result_set(tmp_path / "cand", pass_rate=0.70, unsafe_approval_rate=0.10)

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is False
    assert 0 < DEFAULT_GATE_TOLERANCE < 0.20


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


# ── coverage metrics: the gate counts what the fold drops (EV1 → EV2) ──


def test_one_added_structural_inconclusive_regresses_the_gate(tmp_path: Path) -> None:
    """A candidate identical to the baseline except one structural case flipped
    to inconclusive must fail and name ``inconclusive_rate``.

    The crashed case leaves the unsafe-approval denominator, so the rate the
    gate used to watch cannot rise — the inconclusive rate is the signal that
    a case's evidence went missing, and nothing gated it before.
    """
    from mergecraft.evals.gate import eval_gate

    baseline = _result_set(
        tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10, inconclusive_rate=0.0
    )
    candidate = _result_set(
        tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.10, inconclusive_rate=0.25
    )

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is False
    assert "inconclusive_rate" in report.regressed_metrics
    delta = next(item for item in report.deltas if item.metric == "inconclusive_rate")
    assert delta.baseline == 0.0
    assert delta.candidate == 0.25
    assert delta.regressed is True


def test_all_failed_detection_half_regresses_and_names_failed_case_rate(tmp_path: Path) -> None:
    """A candidate whose every detection case failed — ``cases_run == 0`` and the
    empty fold reporting recall/precision/F1 of ``1.0`` — must fail the gate and
    name ``detection.failed_case_rate``, even though its recall delta is ``>= 0``.

    This is the perfect-run-made-of-nothing: the aggregate says 1.0 because no
    case survived to be scored, so the old recall/precision/F1 comparison sees
    an *improvement*. The failed-case rate is ``1.0`` on an all-failed run.
    """
    from mergecraft.evals.gate import eval_gate

    structural = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate_structural = _result_set(tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.10)

    baseline = _with_detection(
        structural,
        _detection(cases_run=2, cases_failed=0, total_issues=2, total_reported=2, found=1),
    )
    candidate = _with_detection(
        candidate_structural,
        _detection(cases_run=0, cases_failed=2, total_issues=0, total_reported=0, found=0),
    )

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is False
    assert "detection.failed_case_rate" in report.regressed_metrics
    rate = next(item for item in report.deltas if item.metric == "detection.failed_case_rate")
    assert rate.baseline == 0.0
    assert rate.candidate == 1.0
    assert rate.regressed is True
    # The old aggregate signal moved the *right* way (up) and does not regress.
    recall = next(item for item in report.deltas if item.metric == "detection.recall")
    assert recall.candidate >= recall.baseline
    assert recall.regressed is False


def test_dropping_a_low_recall_case_cannot_pass_by_raising_recall(tmp_path: Path) -> None:
    """Dropping a low-recall case from the fold raises aggregate recall, but the
    case is still attempted-and-failed, so ``detection.failed_case_rate`` rises
    and the gate still fails — dropping hard cases can no longer buy a pass.
    """
    from mergecraft.evals.gate import eval_gate

    structural = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate_structural = _result_set(tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.10)

    baseline = _with_detection(
        structural,
        _detection(cases_run=2, cases_failed=1, total_issues=5, total_reported=5, found=2),
    )
    candidate = _with_detection(
        candidate_structural,
        _detection(cases_run=1, cases_failed=1, total_issues=5, total_reported=5, found=4),
    )

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is False
    recall = next(item for item in report.deltas if item.metric == "detection.recall")
    assert recall.candidate > recall.baseline
    assert recall.regressed is False
    rate = next(item for item in report.deltas if item.metric == "detection.failed_case_rate")
    assert rate.candidate > rate.baseline
    assert rate.regressed is True
    assert "detection.failed_case_rate" in report.regressed_metrics


def test_detection_half_is_skipped_when_both_sides_do_not_carry_it(tmp_path: Path) -> None:
    """The committed baseline carries no detection half; the PR-check candidate
    never carries one either. The absent half stays skipped — never fabricated.
    """
    from mergecraft.evals.gate import eval_gate

    baseline = _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10)
    candidate = _result_set(tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.10)

    report = eval_gate(candidate=candidate, baseline=baseline)

    assert report.passed is True
    assert all(not item.metric.startswith("detection.") for item in report.deltas)


def test_require_halves_fails_a_candidate_missing_the_baseline_detection_half(
    tmp_path: Path,
) -> None:
    """Release mode: a candidate that silently drops the detection half the
    baseline carries regresses and names the missing half (EV-D11).

    Without the flag the absent half is skipped as today, which is the PR
    check's behaviour because its candidate never carries detection.
    """
    from mergecraft.evals.gate import eval_gate

    baseline = _with_detection(
        _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10),
        _detection(cases_run=2, cases_failed=0, total_issues=2, total_reported=2, found=1),
    )
    candidate = _result_set(tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.10)

    skipped = eval_gate(candidate=candidate, baseline=baseline)
    assert skipped.passed is True

    required = eval_gate(candidate=candidate, baseline=baseline, require_halves=True)
    assert required.passed is False
    assert any("detection" in metric for metric in required.regressed_metrics), (
        required.regressed_metrics
    )


def test_require_halves_passes_when_both_sides_carry_the_half(tmp_path: Path) -> None:
    """The flag is a presence check, not a second comparison: both sides carrying
    an identical detection half still passes."""
    from mergecraft.evals.gate import eval_gate

    detection = _detection(cases_run=2, cases_failed=0, total_issues=2, total_reported=2, found=1)
    baseline = _with_detection(
        _result_set(tmp_path / "base", pass_rate=0.90, unsafe_approval_rate=0.10),
        detection,
    )
    candidate = _with_detection(
        _result_set(tmp_path / "cand", pass_rate=0.90, unsafe_approval_rate=0.10),
        detection,
    )

    report = eval_gate(candidate=candidate, baseline=baseline, require_halves=True)

    assert report.passed is True
