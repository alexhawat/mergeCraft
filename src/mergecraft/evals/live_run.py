"""Join corpus case -> diff-review findings -> score_findings() (#140, B3, N5).

``evals/benchmark.py`` (structural decision replay) and ``evals/scoring.py``
(finding-location precision/recall/F1) are two disconnected halves —
``run_structural_replay()``'s own docstring names this join as a future
path. This module is that join: a patch-bearing detection-corpus case is
driven through a findings-producing callable (``ReviewFn``), scored against
its recorded baseline via :func:`mergecraft.evals.scoring.score_findings`,
and folded into a :class:`~mergecraft.evals.benchmark.DetectionMetrics`
section on the published :class:`~mergecraft.evals.benchmark.BenchmarkResultSet`.

The ``ReviewFn`` seam is deliberate: the pure orchestration below (case
discovery, scoring, folding) is keyless and deterministic, while producing
findings for real needs a live provider call. ``run_detection`` wires a
default ``ReviewFn`` that shells out in-process to
:func:`mergecraft.offline_review.run_offline_diff_review`; tests inject a
stub at the same seam instead.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

from mergecraft.evals.benchmark import (
    DEFAULT_BENCHMARK_PROVIDERS,
    DEFAULT_RESULTS_DIR,
    BenchmarkResultSet,
    DetectionCase,
    DetectionCaseResult,
    DetectionMetrics,
    run_structural_replay,
)
from mergecraft.evals.scoring import (
    DEFAULT_LINE_SLACK,
    fold_score_reports,
    load_baseline_issues,
    load_reported_findings,
    score_findings,
)
from mergecraft.evals.store import DEFAULT_BANK_DIR
from mergecraft.utils.agent_resolve import has_credentials_for_slug

# Verbatim from `harbor/agent.py`'s `_PATCH_CANDIDATES` — deliberately
# duplicated, not imported, since the `harbor` extra is optional and this
# in-repo corpus must not require it (B3.0 design-gate finding 1). Do not
# extend this tuple; it defines the on-disk filename contract every detection
# case must use.
PATCH_CANDIDATES: Final[tuple[str, ...]] = (
    "task.patch",
    "changes.patch",
    "diff.patch",
    "review.patch",
)
BASELINE_FILENAME: Final[str] = "baseline.json"
DEFAULT_DETECTION_CORPUS_DIR: Final[Path] = Path("evals/bench/mergecraft")

# Two distinct skip reasons (B3.0 finding 3) — never conflated. Case
# discovery is checked before credentials, so an empty corpus always reports
# `SKIP_REASON_NO_CASES`, even when a credential is also missing.
SKIP_REASON_NO_CREDENTIAL: Final[str] = "no live credential"
SKIP_REASON_NO_CASES: Final[str] = "no patch-bearing cases"

ReviewFn = Callable[[DetectionCase], list[dict[str, Any]]]


def discover_detection_cases(
    corpus_dir: Path = DEFAULT_DETECTION_CORPUS_DIR,
) -> list[DetectionCase]:
    """Find every patch-bearing case under ``corpus_dir``.

    A subdirectory without both a recognized patch filename (from
    ``PATCH_CANDIDATES``) and a ``baseline.json`` is silently skipped — a
    decision-only bank case (D7) has neither and must never surface here.
    """
    if not corpus_dir.is_dir():
        return []

    cases: list[DetectionCase] = []
    for case_dir in sorted(corpus_dir.iterdir()):
        if not case_dir.is_dir():
            continue
        baseline_path = case_dir / BASELINE_FILENAME
        patch_path = next(
            (case_dir / name for name in PATCH_CANDIDATES if (case_dir / name).is_file()),
            None,
        )
        if patch_path is None or not baseline_path.is_file():
            continue
        payload = json.loads(baseline_path.read_text(encoding="utf-8"))
        cases.append(
            DetectionCase(
                case_id=case_dir.name,
                patch_path=patch_path,
                baseline_path=baseline_path,
                closed_world=bool(payload.get("closed_world", False)),
            )
        )
    return cases


def run_live_detection(
    cases: list[DetectionCase],
    *,
    provider: str,
    model: str,
    review_fn: ReviewFn,
    results_dir: Path,
    slack: int = DEFAULT_LINE_SLACK,
) -> DetectionMetrics:
    """Drive every case through ``review_fn``, score it, and fold the results.

    Raw findings are persisted per case under ``results_dir/raw-findings/`` —
    a published number must be able to show its work (D9).
    """
    raw_dir = results_dir / "raw-findings"
    raw_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    case_results: list[DetectionCaseResult] = []
    for case in cases:
        baseline_payload = json.loads(case.baseline_path.read_text(encoding="utf-8"))
        issues = load_baseline_issues(baseline_payload)

        raw_rows = review_fn(case)
        (raw_dir / f"{case.case_id}.json").write_text(
            json.dumps({"findings": raw_rows}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        findings = load_reported_findings({"findings": raw_rows})

        report = score_findings(issues, findings, slack=slack, closed_world=case.closed_world)
        reports.append(report)
        case_results.append(
            DetectionCaseResult(
                case_id=case.case_id,
                closed_world=case.closed_world,
                total_issues=report.total_issues,
                total_reported=report.total_reported,
                found=report.found,
                recall=report.recall,
                corpus_confirmed_precision=report.corpus_confirmed_precision,
                f1=report.f1,
                strict_precision=report.strict_precision if case.closed_world else None,
            )
        )

    return DetectionMetrics(
        provider=provider,
        model=model,
        cases_run=len(cases),
        aggregate=fold_score_reports(reports),
        case_results=case_results,
        raw_findings_dir=str(raw_dir),
    )


def _default_review_fn(model: str) -> ReviewFn:
    """Production ``ReviewFn``: run ``diff-review`` in-process for real.

    Not exercised by the RED suite (needs a live provider) — the seam this
    plugs into is what the tests inject a stub at instead (B3.0 finding 4).
    """
    from mergecraft.offline_review import run_offline_diff_review

    def _fn(case: DetectionCase) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="mergecraft-detect-") as tmp:
            json_path = Path(tmp) / "findings.json"
            asyncio.run(
                run_offline_diff_review(
                    cwd=Path.cwd(),
                    diff_file=case.patch_path,
                    model=model,
                    json_path=json_path,
                )
            )
            if not json_path.is_file():
                return []
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                rows = payload.get("findings", [])
                return [row for row in rows if isinstance(row, dict)]
            return []

    return _fn


def run_detection(
    *,
    provider: str,
    model: str,
    corpus_dir: Path = DEFAULT_DETECTION_CORPUS_DIR,
    results_dir: Path,
    review_fn: ReviewFn | None = None,
) -> tuple[DetectionMetrics | None, str | None]:
    """Run detection if possible, or report exactly why it was skipped.

    Returns ``(metrics, None)`` on a real run, or ``(None, skip_reason)``.
    Case discovery is checked before credentials (locked precedence, B3.0
    finding 3): an empty corpus is always the more specific diagnosis.
    """
    cases = discover_detection_cases(corpus_dir)
    if not cases:
        return None, SKIP_REASON_NO_CASES
    if not has_credentials_for_slug(model):
        return None, SKIP_REASON_NO_CREDENTIAL

    resolved_review_fn = review_fn if review_fn is not None else _default_review_fn(model)
    metrics = run_live_detection(
        cases,
        provider=provider,
        model=model,
        review_fn=resolved_review_fn,
        results_dir=results_dir,
    )
    return metrics, None


def run_full_benchmark(
    bank_dir: Path = DEFAULT_BANK_DIR,
    *,
    detection_corpus_dir: Path = DEFAULT_DETECTION_CORPUS_DIR,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
    detection_provider: str = "claude",
    detection_model: str = "claude-sonnet-5",
    review_fn: ReviewFn | None = None,
) -> BenchmarkResultSet:
    """Join structural decision replay with the live detection run.

    The join is additive: the structural section (``metrics``/``pins``/
    ``case_results``) is byte-identical to a bare ``run_structural_replay()``
    call whether or not detection could run alongside it.
    """
    structural = run_structural_replay(bank_dir, providers=providers)
    metrics, skipped_reason = run_detection(
        provider=detection_provider,
        model=detection_model,
        corpus_dir=detection_corpus_dir,
        results_dir=results_dir,
        review_fn=review_fn,
    )
    return structural.model_copy(update={"detection": metrics, "skipped_reason": skipped_reason})


__all__ = [
    "BASELINE_FILENAME",
    "DEFAULT_DETECTION_CORPUS_DIR",
    "PATCH_CANDIDATES",
    "SKIP_REASON_NO_CASES",
    "SKIP_REASON_NO_CREDENTIAL",
    "DetectionCase",
    "DetectionCaseResult",
    "DetectionMetrics",
    "ReviewFn",
    "discover_detection_cases",
    "run_detection",
    "run_full_benchmark",
    "run_live_detection",
]
