"""Reproducible eval-bank replay and benchmark result sets (#140, W9).

The eval bank's per-case replay is pure and keyless — :func:`replay_case`
recomputes verdicts from recorded evidence via :func:`decide_approval`. This
module runs that structural replay across the whole bank and pins judge/rubric/
prompt versions (S5). Live provider finding-location metrics (precision/recall/F1)
are a separate future publication path — not populated by ``run_structural_replay``.
"""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from pydantic import BaseModel, ConfigDict, Field

import mergecraft
from mergecraft.agents.verifier import (
    VERIFIER_RUBRIC_VERSION,
    judge_pin,
    pinned_judge_model,
)
from mergecraft.evals.scoring import DEFAULT_LINE_SLACK, AggregateScoreReport
from mergecraft.evals.store import (
    CASE_STATUS_BLOCKED,
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
    DEFAULT_BANK_DIR,
    Case,
    list_cases,
    replay_case,
)
from mergecraft.modes import modes

RESULT_SET_SCHEMA_VERSION: Final[str] = "1.3.0"
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
    # #140: a commit identifies code, not a release — the distribution
    # version is pinned alongside the commit so published numbers name both.
    # Defaulted to the installed distribution version (not a placeholder) so
    # pre-#140 result sets still validate; `run_structural_replay` passes it
    # explicitly.
    mergecraft_version: str = Field(default_factory=lambda: mergecraft.__version__)
    # D12: every provider a published number covers, pinned by model id +
    # model_pin, never averaged. A missing/empty pin is a hard failure (D9) —
    # a published report never has zero pinned reviewing models. An entry can
    # still carry `model_pinned=False` (honest, D9's "detect" half — no
    # PINNED_JUDGE_MODELS entry exists for e.g. openai yet); this model does
    # not hard-reject that at construction time, because doing so would break
    # every existing structural-replay call for the ("claude", "openai")
    # default pair — no entry pins the entire pipeline could actually run
    # today. `unpinned_providers`/`fully_pinned` below give a real, callable
    # enforcement point for the moment a result set is *published* (D9's
    # "reject" half — B7's job), rather than leaving it as an unchecked
    # promise (mergeCraft self-review, PR #216).
    reviewing_model: dict[str, ReviewingModelPin] = Field(min_length=1)
    scorer_version: str
    line_slack: int

    @property
    def unpinned_providers(self) -> tuple[str, ...]:
        """Providers whose `reviewing_model` entry is not a confirmed pin."""
        return tuple(
            provider
            for provider, pin in sorted(self.reviewing_model.items())
            if not pin.model_pinned
        )

    @property
    def fully_pinned(self) -> bool:
        """True iff every named provider carries a confirmed model pin (D9).

        Structural replay may legitimately produce `False` (see the field
        comment above) — this is the check B7 must call before publishing,
        not a constructor-time invariant.
        """
        return len(self.unpinned_providers) == 0


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

    @property
    def reproducibility_digest(self) -> str:
        """Content hash of this result set, excluding volatile wall-clock fields (#140).

        ``pins.recorded_at`` is the one field allowed to differ between two
        structural replays of the same commit + corpus — everything else must
        compare equal, so the digest is computed over the canonical JSON dump
        with ``recorded_at`` dropped. Two replays at one commit then answer
        "did these runs agree?" with a string compare instead of an eyeball
        diff.
        """
        payload = self.model_dump(mode="json")
        payload["pins"].pop("recorded_at", None)
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class LatencySummary(BaseModel):
    """Percentile latency story of a benchmark run (EV2) — the tail, not the mean."""

    model_config = ConfigDict(extra="forbid")

    p50_ms: float
    p95_ms: float


def _linear_percentile(sorted_sample: list[float], percentile: float) -> float:
    """Linear interpolation between closest ranks over the sorted sample.

    The percentile method is pinned (the numpy default) so two
    implementations cannot disagree on a published number (EV2): rank =
    ``p/100 * (n - 1)``, then interpolate between the bracketing ranks.
    """
    rank = (percentile / 100.0) * (len(sorted_sample) - 1)
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_sample[lower]
    fraction = rank - lower
    return sorted_sample[lower] + fraction * (sorted_sample[upper] - sorted_sample[lower])


def summarize_latencies(durations_ms: list[float]) -> LatencySummary:
    """Fold per-case durations into a p50/p95 summary (EV2).

    Raises on an empty sample — a latency summary over nothing is a missing
    row, never a fabricated 0.0 (D9).
    """
    if not durations_ms:
        msg = "summarize_latencies needs at least one duration"
        raise ValueError(msg)
    ordered = sorted(durations_ms)
    return LatencySummary(
        p50_ms=_linear_percentile(ordered, 50.0),
        p95_ms=_linear_percentile(ordered, 95.0),
    )


# EV2 rollup mapping, derived purely from a row's replay `status` (W-23).
_REPLAY_STATUS_TO_ROLLUP: Final[dict[str, str]] = {
    CASE_STATUS_PASSED: "correct",
    CASE_STATUS_REGRESSION: "incorrect",
    CASE_STATUS_BLOCKED: "inconclusive",
}


def rollup_by_orchestrator_kind(
    rows_by_kind: dict[str, list[CaseReplayRow]],
) -> dict[str, CorpusClassRollup]:
    """Roll replay rows up per orchestrator kind (EV2, W-23).

    Mirrors ``BenchmarkMetrics.by_corpus_class``'s ``CorpusClassRollup``
    shape, but keyed by orchestrator kind (``hybrid`` vs ``llm``), so the
    W-23 comparison is a lookup, not a re-run. A status outside the known
    replay vocabulary folds into ``inconclusive`` — the honest bucket for an
    outcome the rollup cannot classify.
    """
    rollups: dict[str, CorpusClassRollup] = {}
    for kind, rows in rows_by_kind.items():
        counts = {"total": 0, "correct": 0, "incorrect": 0, "inconclusive": 0}
        for row in rows:
            counts["total"] += 1
            counts[_REPLAY_STATUS_TO_ROLLUP.get(row.status, "inconclusive")] += 1
        rollups[kind] = CorpusClassRollup(**counts)
    return rollups


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
        # represents), not proof a defect exists, and neither is trust tier:
        # an untrusted-tier case can still carry a real seeded defect the
        # review missed (D14's "untrusted never approves" is a policy
        # outcome, not a claim that no bug exists). Only `case.closed_world`
        # — an explicit curator assertion, mirroring `scoring.BaselineIssue`'s
        # flag of the same name (D4/D5) — marks a case's `recorded_findings`
        # as complete and confirmed-clean. `issue-75-untrusted-never-approves`
        # sets it because that case genuinely has no seeded defect (its point
        # is the trust-tier policy itself); a hypothetical future untrusted
        # `bench-security-*` case with a real seeded bug would leave it
        # `False` and stay correctly counted as buggy (mergeCraft self-review,
        # PR #216: an earlier version of this override inferred "no defect"
        # from `trust_tier=="untrusted"` alone, which would have silently
        # swallowed exactly that scenario — see
        # `test_untrusted_tier_case_without_closed_world_still_counts_as_buggy`).
        #
        # `recorded_findings=[]` without `closed_world=True` is reviewer
        # *output*, not ground truth that no defect exists — it is exactly
        # the evidence a genuine missed-bug case would produce, and must
        # stay counted as `buggy_unsafe_approval` regardless of trust tier
        # (see `test_trusted_zero_findings_on_a_buggy_case_still_counts_as_unsafe_approval`).
        # A crashed run (`run_succeeded=False`) is excluded either way — its
        # empty `recorded_findings` reflects a missing run, not a confirmed-
        # clean one, and must still count toward `buggy_total` via the
        # `inconclusive` branch below (pinned by
        # `test_crashed_run_on_a_buggy_case_is_inconclusive_not_a_correct_block`).
        confirmed_clean = (
            case.closed_world
            and case.recorded_findings is not None
            and len(case.recorded_findings) == 0
            and case.run_succeeded
        )
        is_buggy = corpus_class != "adversarial_noop" and not confirmed_clean
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
        mergecraft_version=mergecraft.__version__,
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
    update_latest: bool = True,
) -> Path:
    """Persist a result set as JSON under ``evals/results/``.

    ``update_latest=False`` writes only the timestamped file, leaving
    ``latest.json`` untouched. A single-provider detection result (from
    ``mergecraft eval bench``) is an honest partial artifact, not the ≥2-
    provider comparison D12 requires — silently promoting it to "latest"
    would let a downstream consumer mistake it for a complete, published
    report (mergeCraft self-review, PR #216).

    The default filename (when ``filename`` is not given) is provider-
    scoped and carries a random suffix: two ``mergecraft eval bench`` runs
    for different providers started within the same second previously
    shared one ``structural-replay-<timestamp>.json`` name — the raw-
    findings directories were already per-run-unique, but the *result set*
    itself was not, so one provider's publication could silently overwrite
    another's (mergeCraft self-review, PR #216).
    """
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.pins.recorded_at.strftime("%Y%m%dT%H%M%SZ")
    if filename is not None:
        out_name = filename
    else:
        suffix = uuid.uuid4().hex[:8]
        provider_tag = f"-{result.detection.provider}" if result.detection is not None else ""
        out_name = f"structural-replay{provider_tag}-{stamp}-{suffix}.json"
    path = results_dir / out_name
    path.write_text(
        json.dumps(result.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if update_latest:
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
    "LatencySummary",
    "ReviewingModelPin",
    "VersionPins",
    "corpus_class_for",
    "replay_bank",
    "rollup_by_orchestrator_kind",
    "run_structural_replay",
    "summarize_latencies",
    "write_result_set",
]
