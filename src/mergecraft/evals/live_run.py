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
import re
import shutil
import tempfile
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from loguru import logger

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

# Optional per-case subtree holding the case's pre-patch file tree (#220).
CASE_REPO_DIRNAME: Final[str] = "repo"

_RUN_ID_UNSAFE_CHARS: Final[re.Pattern[str]] = re.compile(r"[^A-Za-z0-9._-]+")

# Two distinct skip reasons (B3.0 finding 3) — never conflated. Case
# discovery is checked before credentials, so an empty corpus always reports
# `SKIP_REASON_NO_CASES`, even when a credential is also missing.
SKIP_REASON_NO_CREDENTIAL: Final[str] = "no live credential"
SKIP_REASON_NO_CASES: Final[str] = "no patch-bearing cases"

ReviewFn = Callable[[DetectionCase], list[dict[str, Any]]]


class ReviewRunFailed(RuntimeError):
    """A live review attempt produced no usable signal.

    Raised by a ``ReviewFn`` (auth/rate-limit/agent/structured-output
    failure) — never by orchestration code. ``run_live_detection`` catches
    this per case so a failed run is excluded from scoring and reported as
    ``cases_failed``, rather than silently treated as "reviewed, zero
    findings" — a materially different, better-looking outcome that would
    depress recall/F1 for the wrong reason (mergeCraft self-review, PR #216).
    """


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


def sanitize_run_id_component(value: str) -> str:
    """Flatten ``value`` into one safe path component for a run directory (#219).

    A routed model slug such as ``openrouter/openai/gpt-5`` would otherwise
    split the run id into nested directories when joined onto
    ``raw-findings/``. Every run of unsafe characters collapses to a single
    ``-`` — sanitized, never truncated, so every slug segment survives and
    two different routed models can never collapse into one directory name.
    """
    return _RUN_ID_UNSAFE_CHARS.sub("-", value).strip("-")


def materialize_case_repo(case: DetectionCase, dest: Path) -> Path:
    """Copy the case's ``repo/`` subtree (its pre-patch file tree) into ``dest`` (#220).

    Returns ``dest``. A case without a ``repo/`` subtree yields an empty
    ``dest`` — the corpus-format addition is opt-in per case, and the
    reviewer's cwd stays an isolated scratch directory either way (never
    the corpus checkout or the operator's real tree).
    """
    dest.mkdir(parents=True, exist_ok=True)
    repo_dir = case.patch_path.parent / CASE_REPO_DIRNAME
    if repo_dir.is_dir():
        shutil.copytree(repo_dir, dest, dirs_exist_ok=True)
    return dest


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

    Raw findings are persisted per case under a run-scoped
    ``results_dir/raw-findings/<provider>-<model>-<timestamp>/`` directory —
    a fixed shared path would let a later run silently overwrite an earlier
    publication's evidence (D9: a published number must be able to show its
    work, and keep showing it after the next run).

    A case whose ``review_fn`` raises :class:`ReviewRunFailed` is excluded
    from scoring — its own review never produced a real result, so counting
    it as "reviewed, zero findings" would misrepresent both the case and the
    aggregate metrics. Failed cases are reported separately via
    ``cases_failed``/``failed_case_ids``, never silently dropped.
    """
    # A timestamp alone collides for two runs of the same provider/model
    # within the same second (concurrent or rapid repeated invocations) —
    # append a short random suffix so the directory is collision-resistant,
    # not just usually-distinct (mergeCraft self-review, PR #216).
    run_stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_id = (
        f"{sanitize_run_id_component(provider)}-{sanitize_run_id_component(model)}"
        f"-{run_stamp}-{uuid.uuid4().hex[:8]}"
    )
    raw_dir = results_dir / "raw-findings" / run_id
    raw_dir.mkdir(parents=True, exist_ok=True)

    reports = []
    case_results: list[DetectionCaseResult] = []
    failed_case_ids: list[str] = []
    for case in cases:
        try:
            raw_rows = review_fn(case)
        except ReviewRunFailed as exc:
            logger.warning("detection case {} review failed: {}", case.case_id, exc)
            failed_case_ids.append(case.case_id)
            continue

        baseline_payload = json.loads(case.baseline_path.read_text(encoding="utf-8"))
        issues = load_baseline_issues(baseline_payload)

        (raw_dir / f"{case.case_id}.json").write_text(
            json.dumps({"findings": raw_rows}, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        findings = load_reported_findings({"findings": raw_rows})

        report = score_findings(issues, findings, slack=slack, closed_world=case.closed_world)
        # D12 (OB4) — eval scores are spans AND files: the span inherits the
        # active review.id via the OB1 close-time merge, making the
        # eval↔trace join free. Best-effort; scoring never depends on it.
        try:
            from mergecraft.tracing import current_tracer, get_tracer_from_settings
            from mergecraft.tracing.signals import emit_eval_score

            tracer = current_tracer()
            if tracer is None:
                from mergecraft.config import load_repo_settings

                tracer = get_tracer_from_settings(load_repo_settings(load_learnings_files=False))
            metrics: dict[str, Any] = {
                "recall": report.recall,
                "corpus_confirmed_precision": report.corpus_confirmed_precision,
                "f1": report.f1,
            }
            if case.closed_world:
                metrics["strict_precision"] = report.strict_precision
            if report.blocker_precision is not None:
                metrics["blocker_precision"] = report.blocker_precision
            emit_eval_score(tracer, case_id=case.case_id, metrics=metrics)
        except Exception as exc:
            logger.debug("eval score span skipped for {}: {}", case.case_id, exc)
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
        cases_run=len(case_results),
        cases_failed=len(failed_case_ids),
        failed_case_ids=failed_case_ids,
        aggregate=fold_score_reports(reports),
        case_results=case_results,
        raw_findings_dir=str(raw_dir),
    )


def _default_review_fn(model: str) -> ReviewFn:
    """Production ``ReviewFn``: run ``diff-review`` in-process for real.

    Not exercised by the RED suite (needs a live provider) — the seam this
    plugs into is what the tests inject a stub at instead (B3.0 finding 4).

    ``cwd`` is a fresh scratch directory per case, not the caller's
    real checkout: this in-repo corpus's patches are self-contained diff
    text (B3.0 finding 4 — ``materialize_diff`` never applies a ``--diff``
    file against ``cwd``, it just relays the raw text), several of them name
    paths that do not exist in *any* real tree, and handing the reviewer the
    operator's actual mergeCraft checkout would let real, unrelated source
    and ``.mergecraft/config.yaml`` settings leak into what is supposed to
    be an isolated case (mergeCraft self-review, PR #216). Instead, when the
    case carries a ``repo/`` subtree (its pre-patch file tree), that tree is
    materialized into the scratch directory *before* the review runs, so the
    reviewer sees the case's real repo context (#220) — never the corpus
    checkout, never the operator's tree, and never an empty scratch
    directory when the case provides one.
    """
    from mergecraft.offline_review import run_offline_diff_review

    def _fn(case: DetectionCase) -> list[dict[str, Any]]:
        with tempfile.TemporaryDirectory(prefix="mergecraft-detect-") as tmp:
            scratch = materialize_case_repo(case, Path(tmp))
            json_path = scratch / "findings.json"
            result = asyncio.run(
                run_offline_diff_review(
                    cwd=scratch,
                    diff_file=case.patch_path,
                    model=model,
                    json_path=json_path,
                )
            )
            if not result.success:
                msg = f"{case.case_id}: {result.error or 'diff-review did not succeed'}"
                raise ReviewRunFailed(msg)
            if not json_path.is_file():
                msg = f"{case.case_id}: diff-review succeeded but wrote no findings JSON"
                raise ReviewRunFailed(msg)
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
    detection_provider: str,
    detection_model: str,
    review_fn: ReviewFn | None = None,
) -> BenchmarkResultSet:
    """Join structural decision replay with the live detection run.

    The join is additive: the structural section (``metrics``/``pins``/
    ``case_results``) is byte-identical to a bare ``run_structural_replay()``
    call whether or not detection could run alongside it.

    ``detection_provider``/``detection_model`` are required, not defaulted
    to a specific vendor — the operator's actual configured model (resolved
    the same way ``diff-review`` resolves ``.mergecraft/config.yaml`` /
    ``MERGECRAFT_MODEL``) belongs at the CLI layer (``mergecraft eval
    bench``), not hardcoded here. A previous hardcoded default
    (``"claude-sonnet-5"``, a bare id with no provider prefix) also silently
    broke ``has_credentials_for_slug``'s parsing, making every credential
    check report "no live credential" regardless of what was actually
    configured (mergeCraft self-review, PR #216).
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
    "CASE_REPO_DIRNAME",
    "DEFAULT_DETECTION_CORPUS_DIR",
    "PATCH_CANDIDATES",
    "SKIP_REASON_NO_CASES",
    "SKIP_REASON_NO_CREDENTIAL",
    "DetectionCase",
    "DetectionCaseResult",
    "DetectionMetrics",
    "ReviewFn",
    "discover_detection_cases",
    "materialize_case_repo",
    "run_detection",
    "run_full_benchmark",
    "run_live_detection",
    "sanitize_run_id_component",
]
