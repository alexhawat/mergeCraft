"""#140 — publish reproducible benchmark numbers with full version pins.

RED suite for PR EV1 (sub-wave EV1.1; implementation EV1.2). Wave plan:
``.ignorelocal/waves/04-observability-eval-wave-plan.md``; test-plan doc:
``docs/test-plans/04-observability-eval.md``.

Two contracts block #140's "publish reproducible numbers":

1. **Same commit + same corpus ⇒ same result set.** Pinned via a new
   ``BenchmarkResultSet.reproducibility_digest`` (EV1.2): a content hash over
   the result set *excluding* volatile wall-clock fields (``pins.recorded_at``),
   so two structural replays at one commit compare equal byte-for-byte where it
   matters. Without it, "did these two runs agree?" is an eyeball diff.
2. **Every version pin is recorded.** ``VersionPins`` already carries the
   rubric, scorer, corpus commit, mergeCraft commit, judge pins, mode prompt
   versions and reviewing-model pins — but not the *mergeCraft distribution
   version* (``mergecraft.__version__``). A commit is not a release; #140's
   "full version pins" needs ``VersionPins.mergecraft_version`` (EV1.2).

Both new symbols failed at attribute-access time at RED-suite time
(``AttributeError``), keeping collection clean with the RED signature naming
exactly the missing EV1.2 contract. Reconciled post-EV1.2 (2026-08-17): EV1.2
(commit ``b1b5452``) made both tests XPASS; the non-strict ``green after EV1.2``
xfail markers were removed, so both tests are now clean real passes. Structural
replay is pure and keyless — no live gate involved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import mergecraft
from mergecraft.evals.benchmark import run_structural_replay
from mergecraft.evals.store import Case, add_case
from mergecraft.utils.learnings import LearningProvenance

_WHEN = datetime(2026, 8, 17, 12, 0, 0, tzinfo=UTC)


# ── bank-case fixtures (mirrors tests/evals/test_live_run.py) ──


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
    """A trivially-replayable bank case for the structural replay."""
    return Case(
        id=case_id,
        title=f"reproducibility fixture {case_id}",
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


# ── #140: reproducibility + pins ──


def test_same_commit_yields_the_same_result_set(tmp_path: Path) -> None:
    """Two structural replays of one bank at one commit produce the same result
    set — pinned via ``reproducibility_digest``, which must exclude the
    wall-clock ``recorded_at`` (the one field allowed to differ)."""
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))
    add_case(bank, _bank_case("synthetic-002"))

    first = run_structural_replay(bank, providers=("claude",))
    second = run_structural_replay(bank, providers=("claude",))

    assert first.pins.recorded_at <= second.pins.recorded_at
    assert first.reproducibility_digest  # a non-empty content hash
    assert first.reproducibility_digest == second.reproducibility_digest


def test_result_set_records_every_version_pin(tmp_path: Path) -> None:
    """The published result set records *every* version pin #140 requires —
    including the mergeCraft distribution version, not just its commit."""
    bank = tmp_path / "bank"
    add_case(bank, _bank_case("synthetic-001"))

    result = run_structural_replay(bank, providers=("claude",))
    pins = result.pins

    assert pins.rubric_version
    assert pins.scorer_version
    assert pins.corpus_commit
    assert pins.mergecraft_commit
    assert pins.mode_prompt_versions
    assert "claude" in pins.judge_pins
    assert "claude" in pins.reviewing_model
    # The missing pin (#140): a commit identifies code, not a release.
    assert pins.mergecraft_version == mergecraft.__version__
