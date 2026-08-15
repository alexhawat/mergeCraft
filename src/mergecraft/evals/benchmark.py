"""Reproducible eval-bank replay and benchmark result sets (#140, W9).

The eval bank's per-case replay is pure and keyless — :func:`replay_case`
recomputes verdicts from recorded evidence via :func:`decide_approval`. This
module runs that structural replay across the whole bank and pins judge/rubric/
prompt versions (S5). Live provider finding-location metrics (precision/recall/F1)
are a separate future publication path — not populated by ``run_structural_replay``.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

from mergecraft.agents.verifier import (
    VERIFIER_RUBRIC_VERSION,
    judge_pin,
    pinned_judge_model,
)
from mergecraft.evals.scoring import DEFAULT_LINE_SLACK, AggregateScoreReport
from mergecraft.evals.store import (
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
    DEFAULT_BANK_DIR,
    Case,
    list_cases,
    replay_case,
)
from mergecraft.modes import modes

RESULT_SET_SCHEMA_VERSION: Final[str] = "1.2.0"
DEFAULT_RESULTS_DIR: Final[Path] = Path("evals/results")

# Providers the benchmark names by default (W9.0: ≥2 providers).
DEFAULT_BENCHMARK_PROVIDERS: Final[tuple[str, ...]] = ("claude", "openai")

# Scoring-contract version pinned alongside the reviewing-model identity (N6)
# — bump whenever `evals/scoring.py`'s matching rules change in a way that
# would move a published number.
SCORER_VERSION: Final[str] = "1.0.0"

_CORPUS_ID_PREFIX: Final[tuple[tuple[str, str], ...]] = (
    ("bench-adversarial", "adversarial_noop"),
    ("bench-crossfile", "cross_file"),
    ("bench-security", "security"),
    ("bench-correctness", "correctness"),
)

# `decide_approval()`'s closed verdict vocabulary, split by direction. A
# decision outside `_BLOCK_LIKE_DECISIONS` is treated as wave-through — see
# `docs/dev/test-plans/eval-benchmark-b2-gate.md`'s "inconclusive" section for
# why this can't be derived from the decision string alone for "neutral".
_BLOCK_LIKE_DECISIONS: Final[frozenset[str]] = frozenset(
    {
        "failure",
        "block",
        "request_changes",
        "require_human_review",
        "require_more_tests",
        "quarantine",
        "escalate",
    }
)
# A row is inconclusive when the run itself never produced a real decision —
# either it crashed (`Case.run_succeeded is False`, checked separately by the
# caller) or the replay engine had no evidence to recompute one at all.
_INCONCLUSIVE_DECISIONS: Final[frozenset[str | None]] = frozenset({None, "unavailable"})


class CaseReplayRow(BaseModel):
    """One case's structural replay outcome."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    corpus_class: str
    status: str
    expected_decision: str
    current_decision: str | None
    replayable: bool


class ReviewingModelPin(BaseModel):
    """The pinned identity of the model a provider reviews with (N6, D12).

    Mirrors ``JudgePin``'s ``model_pinned`` field: a provider without a
    ``PINNED_JUDGE_MODELS`` entry still yields a complete pin record, but
    ``model_pinned=False`` marks ``model_id``/``model_pin`` as unconfirmed
    rather than silently presenting an ``"unknown"`` placeholder as if it
    were a real pin (D9 — a reader must be able to tell a confirmed pin
    from a missing one, not just see a string that happens to parse).
    """

    model_config = ConfigDict(extra="forbid")

    model_id: str
    model_pin: str
    model_pinned: bool


class VersionPins(BaseModel):
    """Pinned identities recorded on every published result set."""

    model_config = ConfigDict(extra="forbid")

    rubric_version: str
    judge_pins: dict[str, dict[str, Any]]
    mode_prompt_versions: dict[str, str]
    corpus_commit: str
    recorded_at: datetime
    # N6: the mergeCraft commit itself, promoted from `_git_head_sha()`'s
    # former role as a fallback-only value to a first-class required pin —
    # #140 requires "mergeCraft commit included with published numbers".
    mergecraft_commit: str
    # D12: every provider a published number covers, pinned by model id +
    # model_pin, never averaged. A missing/empty pin is a hard failure (D9) —
    # a published report never has zero pinned reviewing models.
    reviewing_model: dict[str, ReviewingModelPin] = Field(min_length=1)
    scorer_version: str
    line_slack: int


class GateMatrix(BaseModel):
    """The 2x2-plus-inconclusive directional gate outcome matrix (B2, #140)."""

    model_config = ConfigDict(extra="forbid")

    buggy_total: int
    buggy_correct_block: int
    buggy_unsafe_approval: int
    buggy_inconclusive: int
    clean_total: int
    clean_correct_approval: int
    clean_unsafe_block: int
    clean_inconclusive: int


class CorpusClassRollup(BaseModel):
    """Gate outcome counts for one `corpus_class_for()` bucket."""

    model_config = ConfigDict(extra="forbid")

    total: int
    correct: int
    incorrect: int
    inconclusive: int


class BenchmarkMetrics(BaseModel):
    """Metrics from structural replay of the eval bank."""

    model_config = ConfigDict(extra="forbid")

    cases_total: int
    cases_replayable: int
    cases_passed: int
    cases_regression: int
    cases_blocked: int
    decision_replay_pass_rate: float
    # Directional gate metrics (B2, #140) — split the one scalar above into
    # "did the gate wave a real bug through" vs. "did it block a clean PR for
    # nothing", since those are safety-opposite failure modes a single pass
    # rate cannot distinguish.
    unsafe_approval_rate: float
    clean_block_rate: float
    inconclusive_rate: float
    gate_matrix: GateMatrix
    by_corpus_class: dict[str, CorpusClassRollup]


class DetectionCase(BaseModel):
    """One patch-bearing detection-corpus case discovered on disk (B3, N5)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    patch_path: Path
    baseline_path: Path
    closed_world: bool = False


class DetectionCaseResult(BaseModel):
    """One case's live finding-location outcome — mirrors ``CaseReplayRow``'s
    role for structural replay, but for the detection join (B3, N5)."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    closed_world: bool
    total_issues: int
    total_reported: int
    found: int
    recall: float
    corpus_confirmed_precision: float
    f1: float
    # None on an open-world case — `ScoreReport.strict_precision` raises there
    # (D4); never fabricated as a number that doesn't exist.
    strict_precision: float | None = None


class DetectionMetrics(BaseModel):
    """Live finding-location metrics for one provider/model (B3, N5).

    The join `run_structural_replay()`'s own docstring named as a future
    path: corpus case → `diff-review` findings → `score_findings()` →
    folded here. Optional on `BenchmarkResultSet` — see `skipped_reason`
    for why a run may carry neither `detection` nor a fabricated one.
    """

    model_config = ConfigDict(extra="forbid")

    provider: str
    model: str
    # Cases whose review actually produced a scored result — excludes
    # `cases_failed` (a review-attempt failure is not a zero-finding pass).
    cases_run: int
    cases_failed: int = 0
    failed_case_ids: list[str] = Field(default_factory=list)
    aggregate: AggregateScoreReport
    case_results: list[DetectionCaseResult]
    raw_findings_dir: str


class BenchmarkResultSet(BaseModel):
    """Wire shape written under ``evals/results/``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = RESULT_SET_SCHEMA_VERSION
    pins: VersionPins
    metrics: BenchmarkMetrics
    case_results: list[CaseReplayRow]
    # B3, N5: the live finding-location join. `None` when no live run
    # attempted it yet, or when one was attempted but skipped — see
    # `skipped_reason` for which. Both optional (default `None`) so a
    # pre-B3 committed result set with neither key still validates (D3).
    detection: DetectionMetrics | None = None
    skipped_reason: str | None = None


def corpus_class_for(case: Case) -> str:
    """Map a case id/category to the W9.0 corpus bucket."""
    case_id = case.id
    for prefix, bucket in _CORPUS_ID_PREFIX:
        if case_id.startswith(prefix):
            return bucket
    if case.category == "false_positive":
        return "adversarial_noop"
    if "untrusted" in case_id or "narrative" in case_id:
        return "security"
    if "crashed" in case_id:
        return "correctness"
    if case.category in {"missed_finding", "rejected", "reverted"}:
        return "correctness"
    return "correctness"


def _git_head_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except OSError, subprocess.CalledProcessError:
        return "unknown"


def _git_corpus_commit() -> str:
    """Pin the eval case tree, not bare HEAD (reproducible corpus snapshot)."""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD:evals/cases"],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        return out.strip()
    except OSError, subprocess.CalledProcessError:
        return _git_head_sha()


def _mode_prompt_versions() -> dict[str, str]:
    return {mode.name: mode.version for mode in modes}


def _judge_pins(providers: tuple[str, ...]) -> dict[str, dict[str, Any]]:
    pins: dict[str, dict[str, Any]] = {}
    for provider in providers:
        pin = judge_pin(provider=provider)
        pins[provider] = pin.model_dump(mode="json")
    return pins


def _reviewing_model_pins(providers: tuple[str, ...]) -> dict[str, ReviewingModelPin]:
    """Pin the reviewing-model identity per provider (N6, D12).

    Mirrors ``_judge_pins``: structural replay never invokes a live provider,
    but the *configured* pin for each named provider is itself a fact worth
    recording — a report that later adds a live finding-location run (B3) can
    then diff its own recorded model against this structural baseline.
    """
    pins: dict[str, ReviewingModelPin] = {}
    for provider in providers:
        pinned = pinned_judge_model(provider)
        model = pinned or "unknown"
        pins[provider] = ReviewingModelPin(
            model_id=model, model_pin=model, model_pinned=pinned is not None
        )
    return pins


def run_structural_replay(
    bank_dir: Path = DEFAULT_BANK_DIR,
    *,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
) -> BenchmarkResultSet:
    """Replay every case in the bank and assemble a versioned result set."""
    cases = list_cases(bank_dir)
    rows: list[CaseReplayRow] = []
    passed = regression = blocked = 0
    replayable_count = 0

    buggy_total = buggy_correct_block = buggy_unsafe_approval = buggy_inconclusive = 0
    clean_total = clean_correct_approval = clean_unsafe_block = clean_inconclusive = 0
    class_rollup: dict[str, dict[str, int]] = {
        bucket: {"total": 0, "correct": 0, "incorrect": 0, "inconclusive": 0}
        for _, bucket in _CORPUS_ID_PREFIX
    }

    for case in cases:
        replayable = case.is_replayable
        if replayable:
            replayable_count += 1
        diff = replay_case(case, current_decision=None)
        if diff.status == CASE_STATUS_PASSED:
            passed += 1
        elif diff.status == CASE_STATUS_REGRESSION:
            regression += 1
        else:
            blocked += 1

        corpus_class = corpus_class_for(case)
        rows.append(
            CaseReplayRow(
                case_id=case.id,
                corpus_class=corpus_class,
                status=diff.status,
                expected_decision=diff.expected_decision,
                current_decision=diff.current_decision,
                replayable=replayable,
            )
        )

        # Gate-matrix aggregation reads `case.run_succeeded` directly here,
        # where `case` (not just the `CaseReplayRow` built above) is in
        # scope — see the B2.0 design-gate note on why a crashed run and a
        # genuinely clean "neutral" decision can't be told apart from
        # `diff.current_decision` alone.
        #
        # `corpus_class` is a scenario label (which bug family a case
        # represents), not proof a defect exists — `issue-75-untrusted-
        # never-approves` lands in the "security" bucket via corpus_class_for's
        # id-substring heuristic, but records zero findings and completed
        # successfully: there is nothing for the review to have missed, so
        # counting its "neutral" as an unsafe approval blamed the gate for
        # correctly declining to approve an untrusted run. A completed run
        # (`run_succeeded=True`) with a confirmed-empty finding list is
        # therefore never "buggy" regardless of corpus_class. A crashed run
        # (`run_succeeded=False`) is excluded from this override — its empty
        # `recorded_findings` reflects a missing run, not a confirmed-clean
        # one, and must still count toward `buggy_total` via the
        # `inconclusive` branch below (pinned by
        # `test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block`).
        zero_confirmed_findings = (
            case.recorded_findings is not None
            and len(case.recorded_findings) == 0
            and case.run_succeeded
        )
        is_buggy = corpus_class != "adversarial_noop" and not zero_confirmed_findings
        bucket = class_rollup[corpus_class]
        bucket["total"] += 1
        inconclusive = (not case.run_succeeded) or (
            diff.current_decision in _INCONCLUSIVE_DECISIONS
        )

        if inconclusive:
            bucket["inconclusive"] += 1
            if is_buggy:
                buggy_total += 1
                buggy_inconclusive += 1
            else:
                clean_total += 1
                clean_inconclusive += 1
            continue

        blocked_like = diff.current_decision in _BLOCK_LIKE_DECISIONS
        if is_buggy:
            buggy_total += 1
            if blocked_like:
                buggy_correct_block += 1
                bucket["correct"] += 1
            else:
                buggy_unsafe_approval += 1
                bucket["incorrect"] += 1
        else:
            clean_total += 1
            if blocked_like:
                clean_unsafe_block += 1
                bucket["incorrect"] += 1
            else:
                clean_correct_approval += 1
                bucket["correct"] += 1

    total = len(cases)
    pass_rate = (passed / replayable_count) if replayable_count else 0.0

    unsafe_denom = buggy_total - buggy_inconclusive
    unsafe_approval_rate = (buggy_unsafe_approval / unsafe_denom) if unsafe_denom else 0.0
    clean_denom = clean_total - clean_inconclusive
    clean_block_rate = (clean_unsafe_block / clean_denom) if clean_denom else 0.0
    inconclusive_total = buggy_inconclusive + clean_inconclusive
    inconclusive_rate = (inconclusive_total / total) if total else 0.0

    metrics = BenchmarkMetrics(
        cases_total=total,
        cases_replayable=replayable_count,
        cases_passed=passed,
        cases_regression=regression,
        cases_blocked=blocked,
        decision_replay_pass_rate=pass_rate,
        unsafe_approval_rate=unsafe_approval_rate,
        clean_block_rate=clean_block_rate,
        inconclusive_rate=inconclusive_rate,
        gate_matrix=GateMatrix(
            buggy_total=buggy_total,
            buggy_correct_block=buggy_correct_block,
            buggy_unsafe_approval=buggy_unsafe_approval,
            buggy_inconclusive=buggy_inconclusive,
            clean_total=clean_total,
            clean_correct_approval=clean_correct_approval,
            clean_unsafe_block=clean_unsafe_block,
            clean_inconclusive=clean_inconclusive,
        ),
        by_corpus_class={
            bucket: CorpusClassRollup(**counts) for bucket, counts in class_rollup.items()
        },
    )

    pins = VersionPins(
        rubric_version=VERIFIER_RUBRIC_VERSION,
        judge_pins=_judge_pins(providers),
        mode_prompt_versions=_mode_prompt_versions(),
        corpus_commit=_git_corpus_commit(),
        recorded_at=datetime.now(UTC),
        mergecraft_commit=_git_head_sha(),
        reviewing_model=_reviewing_model_pins(providers),
        scorer_version=SCORER_VERSION,
        line_slack=DEFAULT_LINE_SLACK,
    )

    return BenchmarkResultSet(pins=pins, metrics=metrics, case_results=rows)


def write_result_set(
    result: BenchmarkResultSet,
    *,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    filename: str | None = None,
) -> Path:
    """Persist a result set as JSON under ``evals/results/``."""
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.pins.recorded_at.strftime("%Y%m%dT%H%M%SZ")
    out_name = filename or f"structural-replay-{stamp}.json"
    path = results_dir / out_name
    path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    latest = results_dir / "latest.json"
    latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return path


def replay_bank(
    bank_dir: Path = DEFAULT_BANK_DIR,
    *,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
) -> tuple[BenchmarkResultSet, Path]:
    """Run structural replay and write the versioned result set."""
    result = run_structural_replay(bank_dir, providers=providers)
    path = write_result_set(result, results_dir=results_dir)
    return result, path


__all__ = [
    "DEFAULT_BENCHMARK_PROVIDERS",
    "DEFAULT_RESULTS_DIR",
    "RESULT_SET_SCHEMA_VERSION",
    "SCORER_VERSION",
    "BenchmarkMetrics",
    "BenchmarkResultSet",
    "CaseReplayRow",
    "CorpusClassRollup",
    "DetectionCase",
    "DetectionCaseResult",
    "DetectionMetrics",
    "GateMatrix",
    "ReviewingModelPin",
    "VersionPins",
    "corpus_class_for",
    "replay_bank",
    "run_structural_replay",
    "write_result_set",
]
