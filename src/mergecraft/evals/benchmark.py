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

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.verifier import VERIFIER_RUBRIC_VERSION, judge_pin
from mergecraft.evals.store import (
    CASE_STATUS_PASSED,
    CASE_STATUS_REGRESSION,
    DEFAULT_BANK_DIR,
    Case,
    list_cases,
    replay_case,
)
from mergecraft.modes import modes

RESULT_SET_SCHEMA_VERSION: Final[str] = "1.0.0"
DEFAULT_RESULTS_DIR: Final[Path] = Path("evals/results")

# Providers the benchmark names by default (W9.0: ≥2 providers).
DEFAULT_BENCHMARK_PROVIDERS: Final[tuple[str, ...]] = ("claude", "openai")

_CORPUS_ID_PREFIX: Final[tuple[tuple[str, str], ...]] = (
    ("bench-adversarial", "adversarial_noop"),
    ("bench-crossfile", "cross_file"),
    ("bench-security", "security"),
    ("bench-correctness", "correctness"),
)


class CaseReplayRow(BaseModel):
    """One case's structural replay outcome."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    corpus_class: str
    status: str
    expected_decision: str
    current_decision: str | None
    replayable: bool


class VersionPins(BaseModel):
    """Pinned identities recorded on every published result set."""

    model_config = ConfigDict(extra="forbid")

    rubric_version: str
    judge_pins: dict[str, dict[str, Any]]
    mode_prompt_versions: dict[str, str]
    corpus_commit: str
    recorded_at: datetime


class BenchmarkMetrics(BaseModel):
    """Metrics from structural replay of the eval bank."""

    model_config = ConfigDict(extra="forbid")

    cases_total: int
    cases_replayable: int
    cases_passed: int
    cases_regression: int
    cases_blocked: int
    decision_replay_pass_rate: float


class BenchmarkResultSet(BaseModel):
    """Wire shape written under ``evals/results/``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = RESULT_SET_SCHEMA_VERSION
    pins: VersionPins
    metrics: BenchmarkMetrics
    case_results: list[CaseReplayRow]


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
        rows.append(
            CaseReplayRow(
                case_id=case.id,
                corpus_class=corpus_class_for(case),
                status=diff.status,
                expected_decision=diff.expected_decision,
                current_decision=diff.current_decision,
                replayable=replayable,
            )
        )

    total = len(cases)
    pass_rate = (passed / replayable_count) if replayable_count else 0.0

    metrics = BenchmarkMetrics(
        cases_total=total,
        cases_replayable=replayable_count,
        cases_passed=passed,
        cases_regression=regression,
        cases_blocked=blocked,
        decision_replay_pass_rate=pass_rate,
    )

    pins = VersionPins(
        rubric_version=VERIFIER_RUBRIC_VERSION,
        judge_pins=_judge_pins(providers),
        mode_prompt_versions=_mode_prompt_versions(),
        corpus_commit=_git_corpus_commit(),
        recorded_at=datetime.now(UTC),
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
    "BenchmarkMetrics",
    "BenchmarkResultSet",
    "CaseReplayRow",
    "VersionPins",
    "corpus_class_for",
    "replay_bank",
    "run_structural_replay",
    "write_result_set",
]
