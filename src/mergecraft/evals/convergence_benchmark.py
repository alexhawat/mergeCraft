"""Convergence benchmark replay — multi-round eval harness (RC6, W10)."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

import mergecraft
from mergecraft.agents.verifier import VERIFIER_RUBRIC_VERSION
from mergecraft.evals.benchmark import (
    DEFAULT_BENCHMARK_PROVIDERS,
    DEFAULT_RESULTS_DIR,
    SCORER_VERSION,
    BenchmarkMetrics,
    BenchmarkResultSet,
    GateMatrix,
    VersionPins,
    _judge_pins,
    _mode_prompt_versions,
    _reviewing_model_pins,
    write_result_set,
)
from mergecraft.evals.convergence import (
    ConvergenceCaseResult,
    ConvergenceMetrics,
    ConvergenceRound,
    fold_convergence_reports,
    score_convergence,
)
from mergecraft.evals.convergence_store import convergence_rounds_from_case, list_multi_round_cases
from mergecraft.evals.scoring import DEFAULT_LINE_SLACK
from mergecraft.evals.store import DEFAULT_BANK_DIR
from mergecraft.findings.ledger import FindingLedger

RECALL_PASS_CORPUS_PATH: Final[Path] = Path("evals/corpora/recall_pass_corpus.json")
_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
PRE_W1_LEAKAGE_BASELINE_SCENARIO: Final[str] = "pre-w1-overflow-leakage"


class RecallPassCorpusReport(BaseModel):
    """Recall-pass corpus gate — with vs without the deferred recall lane."""

    model_config = ConfigDict(extra="forbid")

    with_recall: ConvergenceMetrics
    without_recall: ConvergenceMetrics


def _git_head_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _git_corpus_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD:evals/bank"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _resolved_recall_pass_corpus_path() -> Path:
    if RECALL_PASS_CORPUS_PATH.is_file():
        return RECALL_PASS_CORPUS_PATH
    checkout = _REPO_ROOT / RECALL_PASS_CORPUS_PATH
    if checkout.is_file():
        return checkout
    msg = f"recall pass corpus does not exist: {RECALL_PASS_CORPUS_PATH}"
    raise FileNotFoundError(msg)


def _load_recall_pass_corpus() -> tuple[str, list[tuple[str, str, str]]]:
    payload = json.loads(_resolved_recall_pass_corpus_path().read_text(encoding="utf-8"))
    diff_text = str(payload["diff"])
    cases: list[tuple[str, str, str]] = []
    for row in payload["cases"]:
        cases.append((str(row["id"]), str(row["drafted"]), str(row["missed"])))
    return diff_text, cases


def _recall_round_one(
    *,
    case_id: str,
    drafted_body: str,
    missed_body: str,
    with_recall: bool,
    diff_text: str,
) -> ConvergenceRound:
    from mergecraft.review_taxonomy import finding_fingerprint

    path = "src/app.py"
    drafted_fp = finding_fingerprint(path=path, body=drafted_body)
    missed_fp = finding_fingerprint(path="src/util.py", body=missed_body)
    drafted_row = {
        "fingerprint": drafted_fp,
        "path": path,
        "start_line": 12,
        "end_line": 12,
        "body": drafted_body,
    }
    missed_row = {
        "fingerprint": missed_fp,
        "path": "src/util.py",
        "start_line": 42,
        "end_line": 42,
        "body": missed_body,
    }
    ledger = FindingLedger()
    ledger.record(drafted_fp, "open", source=case_id, round_index=1)
    generated = [drafted_fp]
    findings = [drafted_row]
    if with_recall:
        ledger.record(
            missed_fp,
            "deferred",
            source=case_id,
            round_index=1,
            reason="path:src/util.py",
        )
        generated.append(missed_fp)
        findings.append(missed_row)
    return ConvergenceRound(
        round_index=1,
        ledger=ledger,
        findings=findings,
        generated_fingerprints=generated,
        diff_text=diff_text,
    )


def _recall_round_two(*, case_id: str, missed_body: str, diff_text: str) -> ConvergenceRound:
    from mergecraft.review_taxonomy import finding_fingerprint

    missed_fp = finding_fingerprint(path="src/util.py", body=missed_body)
    ledger = FindingLedger()
    ledger.record(missed_fp, "open", source=case_id, round_index=2)
    return ConvergenceRound(
        round_index=2,
        ledger=ledger,
        findings=[
            {
                "fingerprint": missed_fp,
                "path": "src/util.py",
                "start_line": 42,
                "end_line": 42,
                "body": missed_body,
            }
        ],
        generated_fingerprints=[missed_fp],
        diff_text=diff_text,
    )


def _score_recall_corpus(*, with_recall: bool) -> ConvergenceMetrics:
    diff_text, cases = _load_recall_pass_corpus()
    case_results: list[ConvergenceCaseResult] = []
    for case_id, drafted, missed in cases:
        report = score_convergence(
            [
                _recall_round_one(
                    case_id=case_id,
                    drafted_body=drafted,
                    missed_body=missed,
                    with_recall=with_recall,
                    diff_text=diff_text,
                ),
                _recall_round_two(case_id=case_id, missed_body=missed, diff_text=diff_text),
            ]
        )
        case_results.append(ConvergenceCaseResult(case_id=case_id, report=report))
    return fold_convergence_reports(case_results)


def evaluate_recall_pass_corpus() -> RecallPassCorpusReport:
    """Score the structural recall-pass corpus with and without deferred recall."""
    without_recall = _score_recall_corpus(with_recall=False)
    with_recall = _score_recall_corpus(with_recall=True)
    return RecallPassCorpusReport(with_recall=with_recall, without_recall=without_recall)


@lru_cache(maxsize=1)
def load_recall_pass_w0_baseline() -> ConvergenceMetrics:
    """Return the W0 recall-pass baseline (no deferred recall lane).

    ``mean_first_pass_recall`` is pinned at ``0.5`` — the pre-recall-pass W0
    floor used by the W7 gate. ``cases_total``, leakage, and per-case rows
    derive from :func:`_score_recall_corpus` with ``with_recall=False``.
    """
    scored = _score_recall_corpus(with_recall=False)
    return ConvergenceMetrics(
        cases_total=scored.cases_total,
        mean_first_pass_recall=0.5,
        mean_leakage_rate=scored.mean_leakage_rate,
        case_results=scored.case_results,
    )


def build_pre_w1_leakage_round() -> ConvergenceRound:
    """Synthetic round-one scenario modelling RC1/RC2 pre-W1 overflow leakage."""
    from mergecraft.review_taxonomy import finding_fingerprint

    path = "src/app.py"
    bodies = [
        f"inline overflow fixture {index} — pre-W1 leakage baseline" for index in range(1, 12)
    ]
    fingerprints = [finding_fingerprint(path=path, body=body) for body in bodies]
    findings = [
        {
            "fingerprint": fp,
            "path": path,
            "start_line": 10 + index,
            "end_line": 10 + index,
            "body": body,
        }
        for index, (fp, body) in enumerate(zip(fingerprints, bodies, strict=True))
    ]
    ledger = FindingLedger()
    for index, fingerprint in enumerate(fingerprints):
        if index < 8:
            ledger.record(fingerprint, "open", source="test", round_index=1)
        else:
            ledger.record(fingerprint, "unpublished", source="test", round_index=1)
    diff_text = """\
diff --git a/src/app.py b/src/app.py
index 1111111..2222222 100644
--- a/src/app.py
+++ b/src/app.py
@@ -10,3 +10,14 @@ def handler():
     pass
+    # eleven agent findings generated; only eight inline slots
"""
    return ConvergenceRound(
        round_index=1,
        ledger=ledger,
        findings=findings,
        generated_fingerprints=fingerprints,
        diff_text=diff_text,
    )


def load_convergence_scenarios(
    bank_dir: Path = DEFAULT_BANK_DIR,
    *,
    include_builtin_baseline: bool = False,
) -> list[tuple[str, list[ConvergenceRound]]]:
    """Load multi-round convergence scenarios from the eval bank (W10)."""
    scenarios: list[tuple[str, list[ConvergenceRound]]] = [
        (case.id, convergence_rounds_from_case(case)) for case in list_multi_round_cases(bank_dir)
    ]
    if include_builtin_baseline:
        scenarios.append((PRE_W1_LEAKAGE_BASELINE_SCENARIO, [build_pre_w1_leakage_round()]))
    return scenarios


def run_convergence_eval(
    scenarios: list[tuple[str, list[ConvergenceRound]]] | None = None,
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
    include_builtin_baseline: bool = False,
) -> BenchmarkResultSet:
    """Score multi-round scenarios and fold convergence metrics (RC6, W10)."""
    _assert_recall_pass_corpus_gate()
    if scenarios is None:
        scenarios = load_convergence_scenarios(
            bank_dir,
            include_builtin_baseline=include_builtin_baseline,
        )
    if not scenarios:
        scenarios = [(PRE_W1_LEAKAGE_BASELINE_SCENARIO, [build_pre_w1_leakage_round()])]
    case_results = [
        ConvergenceCaseResult(case_id=case_id, report=score_convergence(rounds))
        for case_id, rounds in scenarios
    ]
    convergence = fold_convergence_reports(case_results)
    metrics = BenchmarkMetrics(
        cases_total=convergence.cases_total,
        cases_replayable=0,
        cases_passed=0,
        cases_regression=0,
        cases_blocked=0,
        decision_replay_pass_rate=0.0,
        unsafe_approval_rate=0.0,
        clean_block_rate=0.0,
        inconclusive_rate=0.0,
        gate_matrix=GateMatrix(
            buggy_total=0,
            buggy_correct_block=0,
            buggy_unsafe_approval=0,
            buggy_inconclusive=0,
            clean_total=0,
            clean_correct_approval=0,
            clean_unsafe_block=0,
            clean_inconclusive=0,
        ),
        by_corpus_class={},
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
    return BenchmarkResultSet(
        pins=pins,
        metrics=metrics,
        case_results=[],
        convergence=convergence,
    )


def replay_convergence(
    *,
    bank_dir: Path = DEFAULT_BANK_DIR,
    results_dir: Path = DEFAULT_RESULTS_DIR,
    providers: tuple[str, ...] = DEFAULT_BENCHMARK_PROVIDERS,
    scenarios: list[tuple[str, list[ConvergenceRound]]] | None = None,
    include_builtin_baseline: bool = False,
) -> tuple[BenchmarkResultSet, Path]:
    """Run convergence eval and write a versioned result set under ``evals/results/``."""
    result = run_convergence_eval(
        scenarios,
        bank_dir=bank_dir,
        providers=providers,
        include_builtin_baseline=include_builtin_baseline,
    )
    path = write_result_set(result, results_dir=results_dir, update_latest=False)
    return result, path


def _assert_recall_pass_corpus_gate() -> None:
    """Fail closed when the recall-pass A/B corpus does not improve first-pass recall."""
    report = evaluate_recall_pass_corpus()
    baseline = load_recall_pass_w0_baseline()
    if report.with_recall.mean_first_pass_recall <= report.without_recall.mean_first_pass_recall:
        msg = "recall-pass corpus gate failed: with-recall first-pass recall did not improve"
        raise ValueError(msg)
    if report.with_recall.mean_first_pass_recall <= baseline.mean_first_pass_recall:
        msg = "recall-pass corpus gate failed: with-recall first-pass recall below W0 baseline"
        raise ValueError(msg)


__all__ = [
    "PRE_W1_LEAKAGE_BASELINE_SCENARIO",
    "RecallPassCorpusReport",
    "build_pre_w1_leakage_round",
    "evaluate_recall_pass_corpus",
    "load_convergence_scenarios",
    "load_recall_pass_w0_baseline",
    "replay_convergence",
    "run_convergence_eval",
]
