"""CI evidence respects base-run order and failure identity (#1321).

- The newest base run of a workflow decides; an older same-fingerprint failure
  is evidence only and cannot clear a failure the newest base run passed.
- Failure fingerprints hash the job and the specific diagnostic, never just
  GitHub's generic "Process completed with exit code 1" trailer.
- Failed runs past the log-analysis cap are still recorded as blocking findings.
- A merged analyzer status table reports each tool's newest status.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.ci.base_runs import _fingerprint_for_logs
from mergecraft.ci.evidence import ci_evidence_findings
from mergecraft.ci.flaky import classify_failure
from mergecraft.ci.intelligence import run_ci_intelligence
from mergecraft.ci.review import _base_status_for_cluster
from mergecraft.mcp.analyzers import _store_run_state
from mergecraft.mcp.tool_state import AnalyzerRunKey, AnalyzerRunState, AnalyzerStatusRow
from mergecraft.scm.types import ListedItems
from tests.ci.test_base_branch_runs import HEAD_SHA, _base_run, _ctx, _Github, _zip

_LINT_A = (
    "2026-10-01T10:00:00.0000000Z ##[group]Run make lint\n"
    "2026-10-01T10:00:01.0000000Z src/a.py:3:1: F401 `os` imported but unused\n"
    "2026-10-01T10:00:01.5000000Z Found 1 error.\n"
    "2026-10-01T10:00:02.0000000Z ##[error]Process completed with exit code 1.\n"
)
_LINT_B = (
    "2026-10-02T11:00:00.0000000Z ##[group]Run make lint\n"
    "2026-10-02T11:00:01.0000000Z src/c.py:7:5: F841 local variable `x` is assigned to but never used\n"
    "2026-10-02T11:00:01.5000000Z Found 1 error.\n"
    "2026-10-02T11:00:02.0000000Z ##[error]Process completed with exit code 1.\n"
)
_LINT_A_SAME_FILE_OTHER_RULE = _LINT_A.replace(
    "src/a.py:3:1: F401 `os` imported but unused", "src/a.py:9:5: E711 comparison to None"
)
_FAILING_TEST = (
    "2026-10-01T10:00:00.0000000Z ##[group]Run make test\n"
    "2026-10-01T10:00:01.0000000Z FAILED tests/test_billing.py::test_total - AssertionError\n"
    "2026-10-01T10:00:02.0000000Z ##[error]Process completed with exit code 2.\n"
)


# ── F11: base-run order ──────────────────────────────────────────────────────


def test_newest_passing_base_run_outranks_an_older_failure() -> None:
    verdict = classify_failure(
        fingerprint="fp",
        attempts=[{"conclusion": "failure"}],
        base_branch_runs=[
            {"ref": "main@new", "conclusion": "success", "fingerprint": "fp", "workflow": "CI"},
            {"ref": "main@old", "conclusion": "failure", "fingerprint": "fp", "workflow": "CI"},
        ],
    )
    assert verdict.classification == "stable"
    assert verdict.blame_on_author is True
    assert any("main@old" in line for line in verdict.evidence)


def test_newest_failing_base_run_still_clears_as_pre_existing() -> None:
    verdict = classify_failure(
        fingerprint="fp",
        attempts=[{"conclusion": "failure"}],
        base_branch_runs=[
            {"ref": "main@new", "conclusion": "failure", "fingerprint": "fp", "workflow": "CI"},
            {"ref": "main@old", "conclusion": "success", "fingerprint": "fp", "workflow": "CI"},
        ],
    )
    assert verdict.classification == "pre_existing"
    assert verdict.blame_on_author is False


def test_base_status_for_cluster_reads_the_newest_run() -> None:
    runs = [
        {"ref": "main@new", "conclusion": "success", "fingerprint": "fp", "workflow": "CI"},
        {"ref": "main@old", "conclusion": "failure", "fingerprint": "fp", "workflow": "CI"},
    ]
    status = _base_status_for_cluster(
        "fp", base_branch_runs=runs, base_branch_status=None, cluster_count=1
    )
    assert status == "success"


@pytest.mark.asyncio
async def test_fixed_base_branch_does_not_clear_a_pr_failure(tmp_path: Path) -> None:
    """End to end: base runs newest-first are [success, failure-with-same-fingerprint]."""
    github = _Github(
        base_runs=[_base_run(101, "success"), _base_run(100, "failure")],
        base_logs={101: "", 100: _FAILING_TEST},
        head_log=_FAILING_TEST,
    )
    payload = await run_ci_intelligence(
        _ctx(tmp_path, github), check_suite_id=9, pr_diff_paths=["README.md"]
    )
    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]
    assert payload["stats"]["unattributedCount"] == 1


# ── F12: fingerprint material ────────────────────────────────────────────────


def test_two_different_lint_failures_get_different_fingerprints() -> None:
    assert _fingerprint_for_logs("CI", 1, _LINT_A) != _fingerprint_for_logs("CI", 2, _LINT_B)


def test_same_file_different_diagnostic_gets_a_different_fingerprint() -> None:
    assert _fingerprint_for_logs("CI", 1, _LINT_A) != _fingerprint_for_logs(
        "CI", 2, _LINT_A_SAME_FILE_OTHER_RULE
    )


def test_generic_only_failures_in_different_jobs_get_different_fingerprints() -> None:
    """A log with nothing but the exit-code trailer hashes the job as well."""
    trailer_only = "2026-10-01T10:00:02.0000000Z ##[error]Process completed with exit code 1.\n"
    assert _fingerprint_for_logs("lint", 1, trailer_only) != _fingerprint_for_logs(
        "typecheck", 1, trailer_only
    )


def test_one_specific_diagnostic_in_several_jobs_still_clusters() -> None:
    """Cross-job root-cause clustering (K2) keys on the specific diagnostic."""
    assert _fingerprint_for_logs("py3.11", 1, _LINT_A) == _fingerprint_for_logs(
        "py3.12", 2, _LINT_A
    )


def test_same_failure_in_another_run_keeps_its_fingerprint() -> None:
    """Run ids and timestamps are noise: a recurring failure keeps one identity."""
    later = _LINT_A.replace("2026-10-01T10", "2026-10-09T23")
    assert _fingerprint_for_logs("CI", 1, _LINT_A) == _fingerprint_for_logs("CI", 987654, later)


@pytest.mark.asyncio
async def test_unrelated_red_base_lint_does_not_clear_a_new_lint_failure(tmp_path: Path) -> None:
    github = _Github(
        base_runs=[_base_run(100, "failure")], base_logs={100: _LINT_A}, head_log=_LINT_B
    )
    payload = await run_ci_intelligence(
        _ctx(tmp_path, github), check_suite_id=9, pr_diff_paths=["README.md"]
    )
    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]


# ── F13: failed runs past the analysis cap ───────────────────────────────────


class _ManyFailures(_Github):
    """A head check suite with five failed workflow runs."""

    async def list_workflow_runs_for_check_suite(self, owner: str, repo: str, check_suite_id: int):
        _ = (owner, repo, check_suite_id)
        return ListedItems(
            items=[
                {
                    "id": run_id,
                    "name": f"Workflow {run_id}",
                    "workflow_id": 10 + run_id,
                    "conclusion": "failure",
                    "head_sha": HEAD_SHA,
                    "html_url": f"https://example.test/run/{run_id}",
                }
                for run_id in range(1, 6)
            ],
            incomplete=False,
        )

    async def download_workflow_run_logs(self, owner: str, repo: str, run_id: int) -> bytes:
        _ = (owner, repo)
        self.log_downloads.append(run_id)
        return _zip(_FAILING_TEST)


@pytest.mark.asyncio
async def test_failed_runs_past_the_analysis_cap_are_recorded_as_blocking(
    tmp_path: Path,
) -> None:
    github = _ManyFailures(base_runs=[], base_logs={})
    ctx = _ctx(tmp_path, github, with_base=False)
    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert sorted(github.log_downloads) == [1, 2, 3]
    recorded = ci_evidence_findings(ctx.tool_state)
    overflowed = [row for row in recorded if row.rule_id == "ci-unanalyzed-failed-run"]
    assert sorted(row.message for row in overflowed) == [
        "Workflow 4 failed; its logs were not analyzed (analysis cap reached)",
        "Workflow 5 failed; its logs were not analyzed (analysis cap reached)",
    ]
    assert {(row.severity, row.introduced_by_pr, row.source) for row in overflowed} == {
        ("Major", "unknown", "ci")
    }
    assert {e for row in overflowed for e in row.evidence} >= {
        "https://example.test/run/4",
        "https://example.test/run/5",
    }
    assert payload["recordedFindingCount"] == len(recorded)


# ── F20: merged analyzer status rows ─────────────────────────────────────────


def _key(path: str) -> AnalyzerRunKey:
    return AnalyzerRunKey(
        repo_root="/repo",
        changed_files=(path,),
        tier="trusted",
        shell="restricted",
        mode="auto",
        inline_budget=10,
        offline=True,
        base_ref="main",
        diff_digest=path,
    )


def _segment(path: str, status: str, count: int) -> AnalyzerRunState:
    key = _key(path)
    return AnalyzerRunState(
        ran=True,
        analyzers=[AnalyzerStatusRow(id="ruff", status=status, finding_count=count)],
        key=key,
        covered_scope=key,
    )


def test_merged_status_table_reports_the_newest_row_per_analyzer(tmp_path: Path) -> None:
    github = _Github(base_runs=[], base_logs={})
    ctx = _ctx(tmp_path, github)
    _store_run_state(ctx, _segment("a.py", "unavailable", 0))
    _store_run_state(ctx, _segment("b.py", "failed", 2))
    merged = ctx.tool_state.analyzer_run
    assert merged is not None
    assert [(row.id, row.status, row.finding_count) for row in merged.analyzers] == [
        ("ruff", "failed", 2)
    ]
