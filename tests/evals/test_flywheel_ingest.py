"""R5 RED suite — golden-flywheel ingest with mandatory provenance (#738).

Wave plan: the verification/evals/receipts wave plan (R5). Test-plan doc:
``docs/test-plans/30-verification-evals-receipts.md``.

This wave ingests production false positives and human dismissals into the
versioned structural bank (``evals/cases``), each entry carrying an explicit
provenance string. It does **not** build a new eval harness: the bank, the
replay engine, the adjudication tiers and the adjudicator writer all exist.

Pinned contracts:

* **One vocabulary** — ingest writes the same ``provenance`` string the
  adjudication module already reads through
  ``mergecraft.evals.adjudication.tier_for_provenance``. No second vocabulary
  is minted. The persisted string lives on ``Case.label_provenance``.
* **Refuse without provenance** (R-D6) — a candidate with an empty or
  unrecognised provenance string is *dropped*: no case file, no label, tier
  ``none``. An unknown string never resolves to a privileged tier.
* **Refuse to mint ``human``** (R-D6) — a ``human`` claim is only written when
  the candidate carries an ``AdjudicationRecord`` from the existing
  ``adjudicate_label`` writer whose independence is ``independent``. A bare
  ``human`` string, or one backed by a model-tier record, is refused.
* **Structural only, never calibration** (R-D7) — ingested cases join
  ``eval replay-bank`` as structural replay cases and never make a corpus
  calibration claim eligible. One ingested ``agent-seeded`` row sinks an
  otherwise-independent corpus.
* **Logfire counters** — one ``mergecraft.eval.ingest`` span per candidate and
  one ``mergecraft.eval.ingest.summary`` span carrying the ingest and reject
  counts.
* **No new required PR check** (R-D10) — ingest defaults to the same bank
  ``eval replay-bank`` already reads, so no new CI job is needed. The CI guard
  lives in ``tests/ci/test_flywheel_ingest_ci.py``.

House style matches ``tests/evals/test_adjudication.py`` and
``tests/evidence/test_shadow_second_target.py``: helpers at the top, one
behaviour per test, lazy imports for symbols the R5 implementation wave lands.

The R5 implementation wave satisfied every contract below; the reconciliation
run (``f8c575d3-5a2f-433a-9e6a-8c978fcd25d9``) removed the non-strict
``xfail`` markers so these are real passes.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

_HUMAN_SETTINGS: dict[str, object] = {
    "human": {"enabled": True, "independence": "independent"},
}
_LLM_SETTINGS: dict[str, object] = {
    "llm": {"enabled": True, "independence": "model"},
}


# ── helpers ──────────────────────────────────────────────────────────────────


def _human_record() -> Any:
    """An independent ``human`` adjudication record from the existing writer."""
    from mergecraft.evals.adjudication import adjudicate_label

    return adjudicate_label("human", settings=_HUMAN_SETTINGS)


def _llm_record() -> Any:
    """A ``model``-tier record: distinct adjudicator and producer models."""
    from mergecraft.evals.adjudication import adjudicate_label

    return adjudicate_label(
        "llm",
        settings=_LLM_SETTINGS,
        model="judge-2",
        produced_by="judge-1",
    )


def _candidate(**overrides: Any) -> Any:
    """Build a ``FlywheelCandidate`` (lazy import — the symbol lands in R5)."""
    from mergecraft.evals.flywheel import FlywheelCandidate

    base: dict[str, Any] = {
        "case_id": "synthetic-flywheel-001",
        "title": "Production false positive",
        "category": "false_positive",
        "failure_mode": "false_positive",
        "expected_finding": "src/mergecraft/foo.py:42",
        "expected_decision": "neutral",
        "provenance": "agent-seeded",
        "recorded_findings": [],
        "run_succeeded": True,
        "trust_tier": "trusted",
        "body": "# synthetic-flywheel-001\n",
        "pr_number": 42,
        "run_id": "flywheel-1",
        "author_login": "alexhawat",
        "author_association": "OWNER",
    }
    base.update(overrides)
    return FlywheelCandidate(**base)


def _ingest(candidates: list[Any], bank_dir: Path, tracer: Any = None) -> Any:
    """Run the ingest against an explicit bank directory."""
    from mergecraft.evals.flywheel import ingest_flywheel

    return ingest_flywheel(candidates, bank_dir=bank_dir, tracer=tracer)


def _case_text(bank_dir: Path, case_id: str) -> str | None:
    path = bank_dir / f"{case_id}.md"
    return path.read_text(encoding="utf-8") if path.is_file() else None


# ── happy path: ingest writes the case and its provenance ────────────────────


def test_ingest_writes_an_agent_seeded_case_with_its_provenance(tmp_path: Path) -> None:
    """A production FP is written as a structural case carrying its provenance."""
    from mergecraft.evals.adjudication import tier_for_provenance
    from mergecraft.evals.store import load_case

    bank = tmp_path / "cases"
    report = _ingest([_candidate(provenance="agent-seeded")], bank)

    assert report.ingested_count == 1
    outcome = report.outcomes[0]
    assert outcome.ingested is True
    assert outcome.tier == "none"

    case = load_case(bank / "synthetic-flywheel-001.md")
    assert case.label_provenance == "agent-seeded"
    assert tier_for_provenance(case.label_provenance) == "none"


def test_ingest_writes_a_human_adjudicated_case_when_the_record_is_independent(
    tmp_path: Path,
) -> None:
    """An independent ``human`` adjudication is the one way to write ``human``."""
    from mergecraft.evals.adjudication import tier_for_provenance
    from mergecraft.evals.store import load_case

    bank = tmp_path / "cases"
    report = _ingest(
        [_candidate(provenance="human", adjudication=_human_record())],
        bank,
    )

    assert report.ingested_count == 1
    assert report.outcomes[0].tier == "independent"
    case = load_case(bank / "synthetic-flywheel-001.md")
    assert case.label_provenance == "human"
    assert tier_for_provenance(case.label_provenance) == "independent"


def test_ingest_writes_an_llm_adjudicated_case_at_the_model_tier(tmp_path: Path) -> None:
    """A model adjudicator's label is written at tier ``model``, not upgraded."""
    from mergecraft.evals.store import load_case

    bank = tmp_path / "cases"
    report = _ingest(
        [_candidate(provenance="llm-adjudicated", adjudication=_llm_record())],
        bank,
    )

    assert report.ingested_count == 1
    assert report.outcomes[0].tier == "model"
    case = load_case(bank / "synthetic-flywheel-001.md")
    assert case.label_provenance == "llm-adjudicated"


def test_ingest_writes_the_provenance_the_adjudication_module_derives(tmp_path: Path) -> None:
    """One vocabulary: the persisted string is ``provenance_for(record)``."""
    from mergecraft.evals.adjudication import provenance_for
    from mergecraft.evals.store import load_case

    record = _llm_record()
    bank = tmp_path / "cases"
    _ingest([_candidate(provenance=provenance_for(record), adjudication=record)], bank)

    case = load_case(bank / "synthetic-flywheel-001.md")
    assert case.label_provenance == provenance_for(record)


# ── fail-closed: refuse without provenance, drop rather than mint ────────────


def test_ingest_refuses_a_candidate_without_provenance_and_drops_it(tmp_path: Path) -> None:
    """No provenance string means no case: the candidate is dropped, tier none."""
    bank = tmp_path / "cases"
    report = _ingest([_candidate(provenance="")], bank)

    assert report.ingested_count == 0
    assert report.rejected_count == 1
    outcome = report.outcomes[0]
    assert outcome.ingested is False
    assert outcome.tier == "none"
    assert "provenance" in outcome.reason
    assert _case_text(bank, "synthetic-flywheel-001") is None


def test_ingest_refuses_an_unknown_provenance_string(tmp_path: Path) -> None:
    """A made-up string is not a label: dropped, tier ``none``."""
    bank = tmp_path / "cases"
    report = _ingest([_candidate(provenance="totally-made-up")], bank)

    assert report.rejected_count == 1
    assert report.outcomes[0].tier == "none"
    assert _case_text(bank, "synthetic-flywheel-001") is None


def test_ingest_refuses_to_mint_human_without_an_adjudication_record(tmp_path: Path) -> None:
    """R-D6 — a bare ``human`` string cannot mint an independent label."""
    bank = tmp_path / "cases"
    report = _ingest([_candidate(provenance="human", adjudication=None)], bank)

    assert report.rejected_count == 1
    outcome = report.outcomes[0]
    assert outcome.ingested is False
    assert outcome.tier == "none", "an unadjudicated human claim is not independent"
    assert "adjudicat" in outcome.reason
    assert _case_text(bank, "synthetic-flywheel-001") is None


def test_ingest_refuses_a_human_claim_backed_by_a_non_independent_record(
    tmp_path: Path,
) -> None:
    """Declaring ``human`` while carrying a model-tier record is refused."""
    bank = tmp_path / "cases"
    report = _ingest(
        [_candidate(provenance="human", adjudication=_llm_record())],
        bank,
    )

    assert report.rejected_count == 1
    assert report.outcomes[0].tier == "none"
    assert _case_text(bank, "synthetic-flywheel-001") is None


def test_ingest_never_marks_an_agent_seeded_case_human(tmp_path: Path) -> None:
    """An agent-seeded candidate is written as agent-seeded, never ``human``."""
    from mergecraft.evals.store import load_case

    bank = tmp_path / "cases"
    _ingest([_candidate(provenance="agent-seeded")], bank)

    case = load_case(bank / "synthetic-flywheel-001.md")
    assert case.label_provenance == "agent-seeded"
    assert case.label_provenance != "human"


def test_a_rejected_candidate_leaves_no_case_and_no_label(tmp_path: Path) -> None:
    """The reject path writes nothing and reports no path."""
    bank = tmp_path / "cases"
    report = _ingest(
        [_candidate(case_id="synthetic-flywheel-bad", provenance="")],
        bank,
    )

    assert report.rejected[0].path is None
    assert _case_text(bank, "synthetic-flywheel-bad") is None


def test_a_rejected_candidate_does_not_abort_the_batch(tmp_path: Path) -> None:
    """Fail-closed is per candidate: the good rows after a bad one still land."""
    bank = tmp_path / "cases"
    report = _ingest(
        [
            _candidate(case_id="synthetic-flywheel-bad", provenance=""),
            _candidate(case_id="synthetic-flywheel-good", provenance="agent-seeded"),
        ],
        bank,
    )

    assert report.rejected_count == 1
    assert report.ingested_count == 1
    assert _case_text(bank, "synthetic-flywheel-good") is not None
    assert _case_text(bank, "synthetic-flywheel-bad") is None


def test_ingest_of_an_empty_candidate_list_writes_nothing(tmp_path: Path) -> None:
    """Boundary: no candidates, no cases, zero counters."""
    bank = tmp_path / "cases"
    report = _ingest([], bank)

    assert report.ingested_count == 0
    assert report.rejected_count == 0
    assert not list(bank.glob("*.md"))


# ── R-D7: structural replay cases only, never calibration labels ─────────────


def test_ingested_cases_join_the_structural_replay_bank(tmp_path: Path) -> None:
    """An ingested case is a replayable structural case, not a detection label."""
    from mergecraft.evals.benchmark import run_structural_replay
    from mergecraft.evals.store import list_cases

    bank = tmp_path / "cases"
    _ingest([_candidate(recorded_findings=[])], bank)

    assert [case.id for case in list_cases(bank)] == ["synthetic-flywheel-001"]
    result = run_structural_replay(bank)
    assert result.metrics.cases_total == 1
    assert [row.case_id for row in result.case_results] == ["synthetic-flywheel-001"]
    assert result.detection is None, "structural replay carries no calibration claim"


def test_ingested_agent_seeded_cases_are_never_calibration_labels(tmp_path: Path) -> None:
    """R-D7 — one ingested row makes a corpus-wide calibration claim ineligible."""
    from mergecraft.evals.adjudication import calibration_status
    from mergecraft.evals.store import load_case

    bank = tmp_path / "cases"
    _ingest([_candidate(provenance="agent-seeded")], bank)
    case = load_case(bank / "synthetic-flywheel-001.md")

    assert calibration_status([case.label_provenance]).eligible is False
    assert calibration_status(["human", case.label_provenance]).eligible is False


# ── Logfire ingest and reject counters ───────────────────────────────────────


def test_ingest_emits_ingest_and_reject_counters(tmp_path: Path) -> None:
    """One span per candidate plus a summary carrying both counters."""
    from mergecraft.tracing import MemorySink, Tracer

    sink = MemorySink()
    tracer = Tracer(sink=sink, session_id="flywheel-session", run_id="flywheel-run")
    bank = tmp_path / "cases"

    report = _ingest(
        [
            _candidate(case_id="synthetic-flywheel-good", provenance="agent-seeded"),
            _candidate(case_id="synthetic-flywheel-bad", provenance=""),
        ],
        bank,
        tracer=tracer,
    )

    per_case = [event for event in sink.events if event.kind == "mergecraft.eval.ingest"]
    summary = [event for event in sink.events if event.kind == "mergecraft.eval.ingest.summary"]
    assert len(per_case) == 2, "one ingest span per candidate"
    assert len(summary) == 1, "one summary span per ingest run"
    assert summary[0].attrs["mergecraft.eval.ingest.count"] == report.ingested_count == 1
    assert summary[0].attrs["mergecraft.eval.ingest.rejected"] == report.rejected_count == 1

    flags = {
        event.attrs["mergecraft.eval.ingest.case_id"]: event.attrs[
            "mergecraft.eval.ingest.ingested"
        ]
        for event in per_case
    }
    assert flags == {"synthetic-flywheel-good": True, "synthetic-flywheel-bad": False}


# ── R-D10: ingest targets the bank the existing structural gate reads ────────


def test_ingest_targets_the_structural_bank_by_default() -> None:
    """No new CI job is needed: ingested cases land where ``replay-bank`` reads."""
    from mergecraft.evals.flywheel import ingest_flywheel
    from mergecraft.evals.store import DEFAULT_BANK_DIR

    signature = inspect.signature(ingest_flywheel)
    assert signature.parameters["bank_dir"].default == DEFAULT_BANK_DIR


# ── green guards: the existing vocabulary stays fail-closed ──────────────────


def test_empty_and_unknown_provenance_resolve_to_none_not_a_privileged_tier() -> None:
    """GREEN guard — the reader ingest reuses never upgrades an unknown string."""
    from mergecraft.evals.adjudication import tier_for_provenance

    assert tier_for_provenance("") == "none"
    assert tier_for_provenance("   ") == "none"
    assert tier_for_provenance("hand-wavy") == "none"
    assert tier_for_provenance("human") == "independent"
