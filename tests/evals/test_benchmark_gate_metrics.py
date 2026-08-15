"""Directional gate metrics and complete version pins (#140, B2, RED wave).

``evals/benchmark.py`` currently reports one scalar --
``BenchmarkMetrics.decision_replay_pass_rate`` -- that folds every replay
outcome (buggy caught, buggy missed, clean approved, clean falsely blocked)
into a single "did expected match current" ratio. B2 splits that into
**directional** gate metrics that answer the two questions #140 actually
asks:

- Of the cases with a real bug, how often does the gate wave it through
  anyway (``unsafe_approval_rate``)?
- Of the clean/no-op cases, how often does the gate block them for nothing
  (``clean_block_rate``)?

None of the fields below exist on ``BenchmarkMetrics`` / ``VersionPins`` yet.
Every test that references them fails today by ordinary ``AttributeError``
(reading a missing attribute off an already-existing pydantic model instance)
or ``ValidationError`` (constructing a model with ``extra="forbid"`` and a
keyword it does not recognize yet) at call/assertion time -- never at
collection, since every symbol imported below (``BenchmarkMetrics``,
``VersionPins``, ``run_structural_replay``, ...) already exists. The two
exceptions are ``test_decision_replay_pass_rate_is_unchanged_by_the_new_gate_
fields`` and the docstring-scoped parts of ``test_gate_matrix_matches_the_
worked_example`` that only touch pre-existing ``BenchmarkMetrics`` fields --
those are D3 regression guards and are expected to already pass.

See ``docs/dev/test-plans/eval-benchmark-b2-gate.md`` for the B2.0 design-gate
resolution this file pins (buggy/clean classification, the inconclusive rule,
and the exact rate formulas), and ``evals/cases/issue-75-crashed-run-not-
permissive.md`` for the crashed-run scenario ``test_crashed_run_on_a_buggy_
case_is_inconclusive_not_a_correct_block`` mirrors.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from mergecraft.agents.verifier import VERIFIER_RUBRIC_VERSION, judge_pin
from mergecraft.evals.benchmark import (
    RESULT_SET_SCHEMA_VERSION,
    BenchmarkMetrics,
    VersionPins,
    run_structural_replay,
)
from mergecraft.evals.store import Case, add_case
from mergecraft.modes import compute_prompt_version
from mergecraft.utils.learnings import LearningProvenance

_WHEN = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)


# ── case fixtures ──────────────────────────────────────────────────────
#
# Directional outcome is driven purely through the existing
# ``recorded_findings`` / ``run_succeeded`` / ``trust_tier`` inputs that
# ``recompute_decision()`` already consumes (see
# ``tests/evals/test_recompute_decision.py`` for the same technique):
#
# - a ``Critical`` finding -> ``decide_approval`` blocks ("failure")
# - a ``Minor`` (non-blocking) finding, run succeeded, trusted -> "success"
# - zero findings, run succeeded, trusted -> "neutral" (not a block, not an
#   approval -- the reviewer looked and found nothing to flag)
# - ``run_succeeded=False`` -> "neutral" via the *crashed-run* path (D13);
#   this is the ``RunOutcome.infra_error`` / ``.timed_out`` scenario --
#   every non-``passed`` ``RunOutcome`` reaches ``decide_approval`` as
#   ``run_succeeded=False`` (see ``run_outcome.run_succeeded_for_outcome``
#   and ``agents/gates.py::decide_approval``'s docstring).


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


def _finding(severity: str = "Critical") -> dict[str, Any]:
    return {
        "path": "src/a.py",
        "start_line": 1,
        "end_line": 2,
        "message": "boom",
        "severity": severity,
        "confidence": "certain",
        "category": "Functional Correctness",
        "source": "agent",
        "fingerprint": f"fp-{severity.lower()}",
        "tool": "agent",
        "rule_id": "agent:1",
        "introduced_by_pr": "true",
        "evidence": ["x"],
        "remediation": "fix it",
        "autofix": None,
        "cluster_id": None,
    }


def _bench_case(
    *,
    case_id: str,
    findings: list[dict[str, Any]] | None,
    run_succeeded: bool = True,
    expected_decision: str = "neutral",
    trust_tier: str = "trusted",
    closed_world: bool = False,
) -> Case:
    return Case(
        id=case_id,
        title=f"gate-metrics fixture {case_id}",
        category="missed_finding",
        submitted_at=_WHEN,
        run_id="synthetic",
        pr_number=1,
        failure_mode="wrong_decision",
        expected_finding="synthetic",
        expected_decision=expected_decision,
        replay_command=f"mergecraft eval replay {case_id}",
        provenance=_provenance(),
        body="",
        recorded_findings=findings,
        run_succeeded=run_succeeded,
        trust_tier=trust_tier,
        closed_world=closed_world,
    )


def _buggy_blocked(idx: int, *, corpus_class_prefix: str = "bench-correctness") -> Case:
    """A buggy case the gate correctly blocks."""
    return _bench_case(
        case_id=f"{corpus_class_prefix}-blocked-{idx:03d}",
        findings=[_finding(severity="Critical")],
        run_succeeded=True,
        expected_decision="failure",
    )


def _buggy_unsafe(idx: int, *, corpus_class_prefix: str = "bench-correctness") -> Case:
    """A buggy case the gate waves through -- the unsafe-approval scenario."""
    return _bench_case(
        case_id=f"{corpus_class_prefix}-unsafe-{idx:03d}",
        findings=[_finding(severity="Minor")],
        run_succeeded=True,
        expected_decision="success",
    )


def _buggy_inconclusive(idx: int, *, corpus_class_prefix: str = "bench-correctness") -> Case:
    """A buggy case whose run crashed -- RunOutcome.infra_error/.timed_out."""
    return _bench_case(
        case_id=f"{corpus_class_prefix}-crashed-{idx:03d}",
        findings=[],
        run_succeeded=False,
        expected_decision="neutral",
    )


def _clean_approved(idx: int) -> Case:
    """A clean (adversarial_noop) case correctly waved through."""
    return _bench_case(
        case_id=f"bench-adversarial-clean-{idx:03d}",
        findings=[],
        run_succeeded=True,
        expected_decision="neutral",
    )


def _clean_blocked(idx: int) -> Case:
    """A clean case the gate incorrectly blocks -- a false alarm."""
    return _bench_case(
        case_id=f"bench-adversarial-falsealarm-{idx:03d}",
        findings=[_finding(severity="Critical")],
        run_succeeded=True,
        expected_decision="failure",
    )


def _add_all(bank: Path, cases: list[Case]) -> None:
    for case in cases:
        add_case(bank, case)


# ── BenchmarkMetrics: gate matrix + directional rates ──────────────────


def test_gate_matrix_matches_the_worked_example(tmp_path: Path) -> None:
    """21/2 buggy, 24/3 clean -> unsafe approval 8.7%, clean block 11.1% (B2.1)."""
    bank = tmp_path / "bank"
    cases = (
        [_buggy_blocked(i) for i in range(21)]
        + [_buggy_unsafe(i) for i in range(2)]
        + [_clean_approved(i) for i in range(24)]
        + [_clean_blocked(i) for i in range(3)]
    )
    _add_all(bank, cases)

    result = run_structural_replay(bank)

    assert result.metrics.cases_total == 50

    matrix = result.metrics.gate_matrix
    assert matrix.buggy_total == 23
    assert matrix.buggy_correct_block == 21
    assert matrix.buggy_unsafe_approval == 2
    assert matrix.buggy_inconclusive == 0
    assert matrix.clean_total == 27
    assert matrix.clean_correct_approval == 24
    assert matrix.clean_unsafe_block == 3
    assert matrix.clean_inconclusive == 0

    assert result.metrics.unsafe_approval_rate == pytest.approx(2 / 23, abs=1e-4)
    assert result.metrics.clean_block_rate == pytest.approx(3 / 27, abs=1e-4)
    # The plan's own rounding -- pin it exactly, not just within tolerance.
    assert round(result.metrics.unsafe_approval_rate * 100, 1) == 8.7
    assert round(result.metrics.clean_block_rate * 100, 1) == 11.1


def test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block(
    tmp_path: Path,
) -> None:
    """A crashed run must never be credited as a correct block (B2.0 bullet 3).

    Mirrors ``evals/cases/issue-75-crashed-run-not-permissive.md``: a crashed
    run's replay decision is "neutral" via ``decide_approval``'s
    ``run_succeeded=False`` path. The review never actually looked at the
    diff, so the outcome cannot be credited as catching the bug -- but it is
    also not a reviewer waving a real bug through. It must land in its own
    inconclusive bucket, excluded from both directional numerators *and* the
    unsafe-approval-rate denominator, so a spike in infra failures cannot
    quietly improve the reported gate quality.
    """
    bank = tmp_path / "bank"
    _add_all(
        bank,
        [
            _buggy_blocked(0),
            _buggy_blocked(1),
            _buggy_unsafe(0),
            _buggy_inconclusive(0),
        ],
    )

    result = run_structural_replay(bank)

    matrix = result.metrics.gate_matrix
    assert matrix.buggy_total == 4
    assert matrix.buggy_correct_block == 2
    assert matrix.buggy_unsafe_approval == 1
    assert matrix.buggy_inconclusive == 1
    # Not diluted by the crashed run: 1 unsafe approval out of the 3 buggy
    # cases that actually produced a decided (non-inconclusive) outcome.
    assert result.metrics.unsafe_approval_rate == pytest.approx(1 / 3, abs=1e-4)


def test_non_replayable_buggy_case_is_inconclusive_not_silently_dropped(
    tmp_path: Path,
) -> None:
    """A case with no recorded evidence (``recorded_findings=None``) cannot be
    credited as caught or missed -- it must still land in ``inconclusive``,
    not vanish from the matrix or the buggy total.
    """
    bank = tmp_path / "bank"
    _add_all(
        bank,
        [
            _buggy_blocked(0),
            _bench_case(
                case_id="bench-correctness-no-evidence-000",
                findings=None,
                expected_decision="failure",
            ),
        ],
    )

    result = run_structural_replay(bank)

    matrix = result.metrics.gate_matrix
    assert matrix.buggy_total == 2
    assert matrix.buggy_correct_block == 1
    assert matrix.buggy_unsafe_approval == 0
    assert matrix.buggy_inconclusive == 1


def test_gate_matrix_rollup_by_corpus_class(tmp_path: Path) -> None:
    """Per-``corpus_class`` rollup reuses ``corpus_class_for()``'s four
    buckets -- correctness / security / cross_file / adversarial_noop -- not
    a new vocabulary (see B2.0 bullet 2 and the module docstring above).
    """
    bank = tmp_path / "bank"
    _add_all(
        bank,
        [
            _buggy_blocked(0, corpus_class_prefix="bench-correctness"),
            _buggy_unsafe(0, corpus_class_prefix="bench-correctness"),
            _buggy_blocked(0, corpus_class_prefix="bench-security"),
            _buggy_blocked(1, corpus_class_prefix="bench-security"),
            _buggy_blocked(0, corpus_class_prefix="bench-crossfile"),
            _clean_approved(0),
            _clean_blocked(0),
        ],
    )

    result = run_structural_replay(bank)
    by_class = result.metrics.by_corpus_class

    assert by_class["correctness"].total == 2
    assert by_class["correctness"].correct == 1
    assert by_class["correctness"].incorrect == 1
    assert by_class["correctness"].inconclusive == 0

    assert by_class["security"].total == 2
    assert by_class["security"].correct == 2
    assert by_class["security"].incorrect == 0

    assert by_class["cross_file"].total == 1
    assert by_class["cross_file"].correct == 1

    assert by_class["adversarial_noop"].total == 2
    assert by_class["adversarial_noop"].correct == 1
    assert by_class["adversarial_noop"].incorrect == 1


def test_untrusted_tier_zero_findings_is_not_counted_as_buggy(
    tmp_path: Path,
) -> None:
    """An untrusted-tier case whose run *completed*, recorded zero findings,
    AND is curator-confirmed clean (`closed_world=True`) is not "buggy"
    (regression: issue-75-untrusted-never-approves — `run_succeeded=True`,
    `recorded_findings=[]`, `trust_tier="untrusted"`, `closed_world=True`,
    corpus_class="security" via corpus_class_for's id-substring heuristic —
    was previously counted as a `buggy_unsafe_approval` even though approval
    was structurally impossible for this trust tier regardless of findings —
    the mergeCraft self-review on PR #216 caught this: it made the published
    unsafe_approval_rate entirely attributable to a case where the gate
    correctly declined to approve an untrusted run).

    The override keys off `closed_world` — an explicit curator assertion —
    not `trust_tier` alone: a trust tier is a policy classification, not
    ground truth about whether a defect exists. See
    `test_untrusted_tier_case_without_closed_world_still_counts_as_buggy` for
    the case this distinction protects (a genuinely buggy untrusted-tier
    case the review missed, which must stay counted), and
    `test_trusted_zero_findings_on_a_buggy_case_still_counts_as_unsafe_approval`
    for the analogous **trusted** scenario, and
    `test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block`
    for the separate crashed-run (`run_succeeded=False`) case, which must
    also stay counted as buggy via the inconclusive branch.
    """
    bank = tmp_path / "bank"
    _add_all(
        bank,
        [
            _bench_case(
                case_id="bench-security-untrusted-completed-000",
                findings=[],
                run_succeeded=True,
                expected_decision="neutral",
                trust_tier="untrusted",
                closed_world=True,
            )
        ],
    )

    result = run_structural_replay(bank)

    matrix = result.metrics.gate_matrix
    assert matrix.buggy_total == 0
    assert matrix.clean_total == 1
    assert matrix.clean_correct_approval == 1
    assert result.metrics.unsafe_approval_rate == 0.0


def test_untrusted_tier_case_without_closed_world_still_counts_as_buggy(
    tmp_path: Path,
) -> None:
    """The untrusted-tier override must NOT swallow a genuine untrusted-tier
    buggy miss: a case with `trust_tier="untrusted"`, zero recorded findings,
    and `closed_world=False` (the default — no curator assertion that this
    case is clean) is a real seeded-bug case the review missed, and must
    stay counted as `buggy_unsafe_approval` exactly like the trusted-tier
    equivalent below. Trust tier alone was never sufficient ground truth
    that no defect exists (mergeCraft self-review, PR #216: an earlier
    version of this override inferred "no defect" from `trust_tier==
    "untrusted"` alone, which would have silently reclassified this exact
    scenario as clean)."""
    bank = tmp_path / "bank"
    _add_all(
        bank,
        [
            _bench_case(
                case_id="bench-security-untrusted-missed-000",
                findings=[],
                run_succeeded=True,
                expected_decision="neutral",
                trust_tier="untrusted",
                closed_world=False,
            )
        ],
    )

    result = run_structural_replay(bank)

    matrix = result.metrics.gate_matrix
    assert matrix.buggy_total == 1
    assert matrix.buggy_unsafe_approval == 1
    assert matrix.clean_total == 0
    assert result.metrics.unsafe_approval_rate == 1.0


def test_trusted_zero_findings_on_a_buggy_case_still_counts_as_unsafe_approval(
    tmp_path: Path,
) -> None:
    """The narrow untrusted-tier override above must NOT swallow this case:
    a **trusted** run that completed and reported zero findings on a
    genuinely buggy (non-adversarial_noop) case is exactly what
    `unsafe_approval_rate` exists to measure — the review ran, had every
    opportunity to catch the defect, and didn't. `recorded_findings=[]` here
    is reviewer *output*, not proof no defect exists; corpus_class alone
    still marks this a buggy case and it must stay counted as
    `buggy_unsafe_approval` (mergeCraft self-review on PR #216 flagged the
    first version of the untrusted-tier fix for being broad enough to risk
    swallowing exactly this scenario)."""
    bank = tmp_path / "bank"
    _add_all(
        bank,
        [
            _bench_case(
                case_id="bench-correctness-missed-000",
                findings=[],
                run_succeeded=True,
                expected_decision="neutral",
                trust_tier="trusted",
            )
        ],
    )

    result = run_structural_replay(bank)

    matrix = result.metrics.gate_matrix
    assert matrix.buggy_total == 1
    assert matrix.buggy_unsafe_approval == 1
    assert matrix.clean_total == 0
    assert result.metrics.unsafe_approval_rate == 1.0


def test_zero_buggy_or_zero_clean_cases_does_not_divide_by_zero(tmp_path: Path) -> None:
    """An all-clean (or all-buggy) bank must not raise ZeroDivisionError."""
    bank = tmp_path / "bank"
    _add_all(bank, [_clean_approved(0), _clean_approved(1)])

    result = run_structural_replay(bank)

    assert result.metrics.gate_matrix.buggy_total == 0
    assert result.metrics.unsafe_approval_rate == 0.0
    assert result.metrics.clean_block_rate == pytest.approx(0.0, abs=1e-9)


def _full_benchmark_metrics_kwargs() -> dict[str, Any]:
    return {
        "cases_total": 50,
        "cases_replayable": 50,
        "cases_passed": 50,
        "cases_regression": 0,
        "cases_blocked": 0,
        "decision_replay_pass_rate": 1.0,
        "unsafe_approval_rate": 2 / 23,
        "clean_block_rate": 3 / 27,
        "inconclusive_rate": 0.0,
        "gate_matrix": {
            "buggy_total": 23,
            "buggy_correct_block": 21,
            "buggy_unsafe_approval": 2,
            "buggy_inconclusive": 0,
            "clean_total": 27,
            "clean_correct_approval": 24,
            "clean_unsafe_block": 3,
            "clean_inconclusive": 0,
        },
        "by_corpus_class": {
            "correctness": {"total": 5, "correct": 4, "incorrect": 1, "inconclusive": 0},
            "security": {"total": 5, "correct": 5, "incorrect": 0, "inconclusive": 0},
            "cross_file": {"total": 13, "correct": 12, "incorrect": 1, "inconclusive": 0},
            "adversarial_noop": {"total": 27, "correct": 24, "incorrect": 3, "inconclusive": 0},
        },
    }


def test_benchmark_metrics_accepts_the_full_gate_shape_and_still_forbids_extras() -> None:
    """Unit-level pin of the target shape, independent of ``run_structural_replay``."""
    metrics = BenchmarkMetrics(**_full_benchmark_metrics_kwargs())

    dumped = metrics.model_dump(mode="json")
    assert dumped["unsafe_approval_rate"] == pytest.approx(2 / 23, abs=1e-4)
    assert dumped["gate_matrix"]["buggy_correct_block"] == 21
    assert dumped["by_corpus_class"]["adversarial_noop"]["incorrect"] == 3

    with pytest.raises(ValidationError):
        BenchmarkMetrics(**_full_benchmark_metrics_kwargs(), unknown="nope")  # type: ignore[arg-type]


def test_decision_replay_pass_rate_is_unchanged_by_the_new_gate_fields(
    tmp_path: Path,
) -> None:
    """D3 regression guard -- the pre-B2 scalar keeps its pre-B2 formula and
    value. This test already passes today; it must keep passing once the
    gate-matrix fields land alongside it.
    """
    bank = tmp_path / "bank"
    cases = [_buggy_blocked(i) for i in range(3)] + [_clean_approved(i) for i in range(2)]
    _add_all(bank, cases)

    result = run_structural_replay(bank)

    assert result.metrics.cases_total == 5
    assert result.metrics.cases_replayable == 5
    # Every fixture case's expected_decision matches its recomputed current
    # decision, so every case passes structurally, independent of direction.
    assert result.metrics.cases_passed == 5
    assert result.metrics.decision_replay_pass_rate == pytest.approx(1.0)


def test_result_set_schema_version_is_at_least_1_1_0() -> None:
    """B2 bumped 1.0.0 -> 1.1.0 for the gate-matrix fields; B3 bumped it again
    to 1.2.0 for the detection join. Pin the floor B2 actually needs, not an
    exact string a later PR's own version bump would otherwise break."""
    major, minor, _ = (int(part) for part in RESULT_SET_SCHEMA_VERSION.split("."))
    assert (major, minor) >= (1, 1)


# ── VersionPins: N6 pin completion ──────────────────────────────────────

_NEW_PIN_KWARGS: dict[str, Any] = {
    "mergecraft_commit": "abc1234",
    "reviewing_model": {
        "claude": {
            "model_id": "claude-sonnet-5",
            "model_pin": "claude-sonnet-5-20260115",
            "model_pinned": True,
        },
        "openai": {
            "model_id": "gpt-5.1-codex",
            "model_pin": "gpt-5.1-codex-2026-01-01",
            "model_pinned": True,
        },
    },
    "scorer_version": "1.0.0",
    "line_slack": 3,
}


def _old_pin_kwargs() -> dict[str, Any]:
    return {
        "rubric_version": VERIFIER_RUBRIC_VERSION,
        "judge_pins": {"claude": judge_pin(provider="claude").model_dump(mode="json")},
        "mode_prompt_versions": {"stable": compute_prompt_version("stable")},
        "corpus_commit": "deadbeef",
        "recorded_at": _WHEN,
    }


def test_pre_fix_1_2_0_reviewing_model_shape_no_longer_silently_parses() -> None:
    """A PR #216 fix commit added a *required* `ReviewingModelPin.model_pinned`
    field without (at first) bumping the schema version, so an old genuinely-
    1.2.0-shaped result set (written before that fix, no `model_pinned` key
    on its `reviewing_model` entries) would still claim `schema_version ==
    "1.2.0"` while silently failing to parse under the new code -- the exact
    "same version string, no longer mutually parseable" gap the mergeCraft
    self-review caught. `RESULT_SET_SCHEMA_VERSION` was bumped to 1.3.0 to
    make that incompatibility explicit instead of silent; this test builds
    the old 1.2.0 shape directly (no `model_pinned` key at all, not even
    `False`) and confirms it is rejected outright, not silently accepted
    under a stale label."""
    old_pins_dict = {
        **_old_pin_kwargs(),
        "mergecraft_commit": "deadbeef",
        "reviewing_model": {
            "claude": {"model_id": "claude-sonnet-5", "model_pin": "claude-sonnet-5"},
        },
        "scorer_version": "1.0.0",
        "line_slack": 3,
    }
    with pytest.raises(ValidationError):
        VersionPins(**old_pins_dict)


def test_version_pins_round_trips_with_every_n6_field() -> None:
    kwargs = {**_old_pin_kwargs(), **_NEW_PIN_KWARGS}
    pins = VersionPins(**kwargs)

    dumped = pins.model_dump(mode="json")
    assert dumped["mergecraft_commit"] == "abc1234"
    assert dumped["reviewing_model"]["claude"]["model_id"] == "claude-sonnet-5"
    assert dumped["reviewing_model"]["openai"]["model_pin"] == "gpt-5.1-codex-2026-01-01"
    assert dumped["scorer_version"] == "1.0.0"
    assert dumped["line_slack"] == 3

    restored = VersionPins.model_validate(dumped)
    assert restored == pins


@pytest.mark.parametrize("field_name", sorted(_NEW_PIN_KWARGS))
def test_version_pins_n6_fields_are_required_not_optional(field_name: str) -> None:
    """D9 -- a missing pin is a hard failure, not a silently-defaulted None.

    Inspects the pydantic field metadata directly rather than constructing
    with the field omitted: today *none* of the four N6 fields are
    recognized, so any kwargs-minus-one construction would fail on the
    *other* three regardless of which one was actually dropped, masking the
    field this test is meant to isolate. The field-required introspection
    below fails today for exactly one clean reason per field (the field does
    not exist yet) and, once implemented, only passes if that field is
    genuinely required -- an implementer who makes it ``| None = None``
    fails this test too.
    """
    field = VersionPins.model_fields.get(field_name)
    assert field is not None, f"VersionPins has no {field_name!r} field yet (N6)"
    assert field.is_required(), (
        f"{field_name!r} must be a required VersionPins field: a missing pin is a "
        "hard failure (D9), not an optional extra"
    )


def test_version_pins_reviewing_model_rejects_an_empty_pin_set() -> None:
    """D12 -- a published report never has zero pinned reviewing models."""
    kwargs = {**_old_pin_kwargs(), **_NEW_PIN_KWARGS, "reviewing_model": {}}
    with pytest.raises(ValidationError):
        VersionPins(**kwargs)


def test_reviewing_model_pins_flag_unpinned_providers_honestly(tmp_path: Path) -> None:
    """A provider without a `PINNED_JUDGE_MODELS` entry (e.g. openai today --
    only claude has one) still gets a complete `ReviewingModelPin`, but
    `model_pinned=False` so a reader can tell the `"unknown"` model_id/pin
    apart from a genuine pin (D9). Mirrors `JudgePin.model_pinned` -- the
    codebase's existing precedent for exactly this "no pin configured" state
    (mergeCraft self-review on PR #216: substituting "unknown" with no flag
    silently defeated D9's hard-failure invariant for missing pins).
    """
    bank = tmp_path / "bank"
    _add_all(bank, [_clean_approved(0)])

    result = run_structural_replay(bank, providers=("claude", "openai"))

    claude_pin = result.pins.reviewing_model["claude"]
    assert claude_pin.model_pinned is True
    assert claude_pin.model_id == "claude-sonnet-5"

    openai_pin = result.pins.reviewing_model["openai"]
    assert openai_pin.model_pinned is False
    assert openai_pin.model_id == "unknown"
