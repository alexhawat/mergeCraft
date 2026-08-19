"""W9 — published, reproducible benchmark numbers (#140). S5 prompt versions have landed.

Harness + result-set contracts are green. Live precision/recall/F1 in README
is D19-spun-out until an operator runs ``make eval-replay`` with ≥2 keys.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from tests.ci.workflow_support import REPO_ROOT, read_text

from mergecraft.agents.verifier import VERIFIER_RUBRIC_VERSION, JudgePin, judge_pin
from mergecraft.evals.benchmark import (
    RESULT_SET_SCHEMA_VERSION,
    BenchmarkMetrics,
    BenchmarkResultSet,
    CaseReplayRow,
    DetectionMetrics,
    ReviewingModelPin,
    VersionPins,
    corpus_class_for,
    replay_bank,
    run_structural_replay,
    write_result_set,
)
from mergecraft.evals.scoring import AggregateScoreReport
from mergecraft.evals.store import Case, add_case
from mergecraft.modes import compute_prompt_version
from mergecraft.utils.learnings import LearningProvenance

_SPUN_OUT_W9 = pytest.mark.xfail(
    reason="spun out: W9 — live precision/recall/F1 in README needs operator eval-replay (#276)",
    strict=True,
)

_EVAL_HEADING = re.compile(r"eval infrastructure", re.IGNORECASE)
_METRICS = (
    re.compile(r"precision", re.IGNORECASE),
    re.compile(r"recall", re.IGNORECASE),
    re.compile(r"\bF1\b", re.IGNORECASE),
    re.compile(r"false[\s-]*positive|FP[\s-]*rate", re.IGNORECASE),
)
_DATE = re.compile(r"20\d{2}-\d{2}-\d{2}")
_SHA = re.compile(r"\b[0-9a-f]{7,40}\b")


def _result_files() -> list[Path]:
    roots = [REPO_ROOT / "evals" / "results", REPO_ROOT / "evals" / "benchmark"]
    found: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        found.extend(root.rglob("*.json"))
        found.extend(root.rglob("*.jsonl"))
    return found


def _provenance() -> LearningProvenance:
    return LearningProvenance(
        run_id="synthetic",
        pr_number=1,
        source_field="eval_bank",
        author_login="synthetic",
        author_association="OWNER",
        trust_tier="trusted",
        timestamp=datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC),
    )


def _case(*, case_id: str = "synthetic-001", category: str = "missed_finding") -> Case:
    return Case(
        id=case_id,
        title="synthetic harness case",
        category=category,
        submitted_at=datetime(2026, 8, 13, 12, 0, 0, tzinfo=UTC),
        run_id="synthetic",
        pr_number=1,
        failure_mode="missed_finding",
        expected_finding="src/mergecraft/foo.py:1",
        expected_decision="failure",
        replay_command=f"mergecraft eval replay {case_id}",
        provenance=_provenance(),
        body="",
        recorded_findings=[],
        run_succeeded=True,
        trust_tier="trusted",
    )


def _pins() -> VersionPins:
    return VersionPins(
        rubric_version=VERIFIER_RUBRIC_VERSION,
        judge_pins={"claude": judge_pin(provider="claude").model_dump(mode="json")},
        mode_prompt_versions={"stable": compute_prompt_version("stable")},
        corpus_commit="deadbeef",
        recorded_at=datetime(2026, 8, 13, 17, 0, 0, tzinfo=UTC),
        mergecraft_commit="deadbeef",
        reviewing_model={
            "claude": ReviewingModelPin(
                model_id="claude-sonnet-5", model_pin="claude-sonnet-5", model_pinned=True
            )
        },
        scorer_version="1.0.0",
        line_slack=3,
    )


def _empty_gate_kwargs() -> dict[str, Any]:
    """Zeroed gate-matrix fields for a `BenchmarkMetrics` with no cases (B2)."""
    return {
        "unsafe_approval_rate": 0.0,
        "clean_block_rate": 0.0,
        "inconclusive_rate": 0.0,
        "gate_matrix": {
            "buggy_total": 0,
            "buggy_correct_block": 0,
            "buggy_unsafe_approval": 0,
            "buggy_inconclusive": 0,
            "clean_total": 0,
            "clean_correct_approval": 0,
            "clean_unsafe_block": 0,
            "clean_inconclusive": 0,
        },
        "by_corpus_class": {
            bucket: {"total": 0, "correct": 0, "incorrect": 0, "inconclusive": 0}
            for bucket in ("correctness", "security", "cross_file", "adversarial_noop")
        },
    }


@_SPUN_OUT_W9
def test_readme_eval_claim_adjacent_to_dated_metrics_and_corpus_commit() -> None:
    """Do not invent numbers — require a dated precision/recall/F1 + FP-rate + corpus SHA."""
    text = read_text("README.md")
    match = _EVAL_HEADING.search(text)
    assert match is not None, "README eval claim missing"
    start = max(0, match.start() - 800)
    end = min(len(text), match.end() + 1600)
    window = text[start:end]
    missing = [pattern.pattern for pattern in _METRICS if not pattern.search(window)]
    assert not missing, f"README eval claim is not adjacent to metrics {missing}"
    assert _DATE.search(window), "benchmark numbers must be dated"
    assert _SHA.search(window), "corpus commit SHA missing next to the eval claim"


def test_replay_target_or_job_exists_and_is_documented() -> None:
    makefile = read_text("Makefile")
    has_make = re.search(r"^(eval-replay|bench-review|eval-gate)\s*:", makefile, re.MULTILINE)
    assert has_make is not None
    # Structural eval-gate already exists; W9 must add a behavioural replay path.
    assert re.search(r"^eval-replay\s*:", makefile, re.MULTILINE) or _workflow_has_replay(), (
        "no eval-replay Make target or CI replay job"
    )
    docs = read_text("evals/README.md") + read_text("README.md")
    assert re.search(r"replay", docs, re.IGNORECASE)


def _workflow_has_replay() -> bool:
    workflows = REPO_ROOT / ".github" / "workflows"
    for path in workflows.glob("*.yml"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"eval-replay|eval replay|benchmark replay", text, re.IGNORECASE):
            return True
    return False


def test_result_set_records_judge_pins_rubric_and_prompt_versions() -> None:
    """Every published result set names judge pins, rubric versions, and S5 prompt versions."""
    files = _result_files()
    assert files, "no evals/results (or evals/benchmark) result set on disk"
    blob = "\n".join(path.read_text(encoding="utf-8") for path in files)
    lowered = blob.lower()
    assert "judge" in lowered or "JudgePin" in blob
    assert "rubric" in lowered
    assert "prompt" in lowered
    assert "version" in lowered

    pin = judge_pin(provider="claude")
    assert isinstance(pin, JudgePin)
    assert pin.rubric_version == VERIFIER_RUBRIC_VERSION
    assert compute_prompt_version("stable") == compute_prompt_version("stable")
    parsed: list[Any] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".jsonl":
            parsed.extend(json.loads(line) for line in text.splitlines() if line.strip())
        else:
            parsed.append(json.loads(text))
    serialized = json.dumps(parsed)
    assert VERIFIER_RUBRIC_VERSION in serialized or "rubric_version" in serialized
    assert "prompt_version" in serialized or "compute_prompt_version" in serialized


def test_published_metrics_are_not_placeholders() -> None:
    """Refuse fabricated TBD / 0.00 / lorem tables next to the eval claim."""
    text = read_text("README.md")
    match = _EVAL_HEADING.search(text)
    assert match is not None
    window = text[max(0, match.start() - 400) : match.end() + 1600]
    assert not re.search(r"\bTBD\b|\blorem\b|TODO: publish", window, re.IGNORECASE)


def test_s5_prompt_version_helper_is_available() -> None:
    """S5 landed — W9 numbers can name the prompt they ran against."""
    assert compute_prompt_version("a") != compute_prompt_version("b")
    pin = judge_pin(provider="claude")
    assert pin.rubric_version == VERIFIER_RUBRIC_VERSION


@pytest.mark.parametrize(
    ("case_id", "category", "expected_class"),
    [
        ("bench-adversarial-clean-diff", "missed_finding", "adversarial_noop"),
        ("synthetic-fp", "false_positive", "adversarial_noop"),
        ("bench-crossfile-api-signature", "missed_finding", "cross_file"),
        ("bench-security-hardcoded-token", "missed_finding", "security"),
        ("issue-75-untrusted-never-approves", "missed_finding", "security"),
        ("issue-75-narrative-approval", "missed_finding", "security"),
        ("bench-correctness-off-by-one", "missed_finding", "correctness"),
        ("issue-75-crashed-run-not-permissive", "missed_finding", "correctness"),
        ("synthetic-rejected", "rejected", "correctness"),
        ("synthetic-reverted", "reverted", "correctness"),
        ("synthetic-default", "other", "correctness"),
    ],
)
def test_corpus_class_for_maps_id_and_category(
    case_id: str, category: str, expected_class: str
) -> None:
    assert corpus_class_for(_case(case_id=case_id, category=category)) == expected_class


def test_benchmark_result_set_wire_shape_and_rejects_extra_fields() -> None:
    result = BenchmarkResultSet(
        pins=_pins(),
        metrics=BenchmarkMetrics(
            cases_total=0,
            cases_replayable=0,
            cases_passed=0,
            cases_regression=0,
            cases_blocked=0,
            decision_replay_pass_rate=0.0,
            **_empty_gate_kwargs(),
        ),
        case_results=[],
    )
    assert result.schema_version == RESULT_SET_SCHEMA_VERSION
    dumped = result.model_dump(mode="json")
    assert dumped["pins"]["rubric_version"] == VERIFIER_RUBRIC_VERSION
    assert "judge_pins" in dumped["pins"]
    with pytest.raises(ValidationError):
        BenchmarkResultSet(
            pins=_pins(),
            metrics=result.metrics,
            case_results=[],
            unknown="nope",  # type: ignore[call-arg]
        )


def test_run_structural_replay_empty_bank_returns_empty_result_set(tmp_path: Path) -> None:
    bank = tmp_path / "bank"
    bank.mkdir()
    result = run_structural_replay(bank)
    assert isinstance(result, BenchmarkResultSet)
    assert result.metrics.cases_total == 0
    assert result.case_results == []
    assert result.pins.rubric_version == VERIFIER_RUBRIC_VERSION
    assert result.pins.judge_pins


def test_run_structural_replay_records_corpus_class_per_case(tmp_path: Path) -> None:
    bank = tmp_path / "bank"
    add_case(bank, _case(case_id="bench-crossfile-export-removed"))
    result = run_structural_replay(bank)
    assert result.metrics.cases_total == 1
    row = result.case_results[0]
    assert isinstance(row, CaseReplayRow)
    assert row.case_id == "bench-crossfile-export-removed"
    assert row.corpus_class == "cross_file"
    assert row.replayable is True


def test_write_result_set_persists_json_and_latest_mirror(tmp_path: Path) -> None:
    result = BenchmarkResultSet(
        pins=_pins(),
        metrics=BenchmarkMetrics(
            cases_total=0,
            cases_replayable=0,
            cases_passed=0,
            cases_regression=0,
            cases_blocked=0,
            decision_replay_pass_rate=0.0,
            **_empty_gate_kwargs(),
        ),
        case_results=[],
    )
    out = write_result_set(result, results_dir=tmp_path, filename="harness.json")
    assert out == tmp_path / "harness.json"
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["schema_version"] == RESULT_SET_SCHEMA_VERSION
    assert payload["pins"]["rubric_version"] == VERIFIER_RUBRIC_VERSION
    latest = tmp_path / "latest.json"
    assert latest.is_file()


def _aggregate() -> AggregateScoreReport:
    return AggregateScoreReport(
        total_cases=0,
        total_issues=0,
        total_reported=0,
        found=0,
        false_negatives=0,
        unadjudicated=0,
        false_positives=0,
        false_positives_per_case=0.0,
        clean_case_fp_rate=0.0,
    )


def _detection(provider: str) -> DetectionMetrics:
    return DetectionMetrics(
        provider=provider,
        model=f"{provider}/some-model",
        cases_run=0,
        aggregate=_aggregate(),
        case_results=[],
        raw_findings_dir=f"/tmp/{provider}-raw",
    )


def test_write_result_set_default_filename_survives_same_second_different_provider(
    tmp_path: Path,
) -> None:
    """Two `mergecraft eval bench` runs for different providers, started
    within the same second (`recorded_at` fixed identically here to force
    the collision), must not silently overwrite each other's result-set
    file — the default filename previously carried only a 1-second-
    resolution timestamp with no provider or randomness component
    (mergeCraft self-review, PR #216)."""
    same_instant = datetime(2026, 8, 15, 12, 0, 0, tzinfo=UTC)

    def _result(provider: str) -> BenchmarkResultSet:
        pins = _pins()
        pins = pins.model_copy(update={"recorded_at": same_instant})
        return BenchmarkResultSet(
            pins=pins,
            metrics=BenchmarkMetrics(
                cases_total=0,
                cases_replayable=0,
                cases_passed=0,
                cases_regression=0,
                cases_blocked=0,
                decision_replay_pass_rate=0.0,
                **_empty_gate_kwargs(),
            ),
            case_results=[],
            detection=_detection(provider),
        )

    first = write_result_set(_result("claude"), results_dir=tmp_path)
    second = write_result_set(_result("openai"), results_dir=tmp_path)

    assert first != second
    assert first.is_file()
    assert second.is_file()
    assert "claude" in first.name
    assert "openai" in second.name


def test_replay_bank_writes_result_set_and_returns_pair(tmp_path: Path) -> None:
    bank = tmp_path / "bank"
    results = tmp_path / "results"
    add_case(bank, _case(case_id="bench-adversarial-minor-only"))
    result, path = replay_bank(bank, results_dir=results)
    assert isinstance(result, BenchmarkResultSet)
    assert path.is_file()
    assert path.parent == results
    loaded = BenchmarkResultSet.model_validate_json(path.read_text(encoding="utf-8"))
    assert loaded.metrics.cases_total == 1
    assert loaded.case_results[0].corpus_class == "adversarial_noop"
    assert (results / "latest.json").is_file()
