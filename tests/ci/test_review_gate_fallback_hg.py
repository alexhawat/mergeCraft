"""Batch HG RED — approval gate must wait for Codex fallback (#433).

Pins D9: the fail-closed ``mergecraft-approval`` gate must not start until
every review attempt in the workflow (including the Codex fallback) has
finished. The #433 defect is the gate step sampling check-runs in the same job
immediately after the Codex action returns, before ``mergecraft-approval`` is
visible — legitimate approvals read as "review did not complete".

Implementation lands in W14 by splitting the gate into its own job with
``needs:`` on the review-attempts job (or on every attempt job when split).
Fail-closed behaviour stays; this suite only checks ordering.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from tests.ci.review_gate_ordering import (
    APPROVAL_GATE_STEP,
    CODEX_FALLBACK_DECIDE_STEP,
    CODEX_REVIEW_STEP,
    FIXTURE_COMBINED_ATTEMPTS_JOB,
    FIXTURE_FALLBACK_JOB,
    FIXTURE_GATE_JOB,
    FIXTURE_PRIMARY_JOB,
    NOUS_REVIEW_STEP,
    approval_gate_job,
    find_step,
    gate_job_needs_attempt_jobs,
    load_fixture,
    scan_workflows,
)
from tests.ci.workflow_support import REPO_ROOT, as_list, job, load_workflow, read_text

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "workflow_review_gate_hg"
_MERGECRAFT_WORKFLOW = "mergecraft.yml"


def _install_hg_fixtures(tmp_path: Path) -> Path:
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    for src in sorted(_FIXTURES_DIR.glob("*.yml")):
        shutil.copyfile(src, workflows / src.name)
    return workflows


class TestFixtureAnchors:
    """Sanity: fixtures model the #433 race without the production workflow."""

    def test_same_job_fixture_colocates_gate_with_codex_fallback(self) -> None:
        doc = load_fixture("same_job_gate_races_fallback.yml")
        codex = find_step(doc, CODEX_REVIEW_STEP)
        gate = find_step(doc, APPROVAL_GATE_STEP)
        assert codex is not None
        assert gate is not None
        assert codex.job == gate.job == "review"
        assert gate.index > codex.index

    def test_split_fixture_gate_omits_codex_fallback_from_needs(self) -> None:
        gate = job(load_fixture("split_attempt_jobs.yml"), FIXTURE_GATE_JOB)
        assert as_list(gate.get("needs")) == [FIXTURE_PRIMARY_JOB]

    def test_good_split_fixture_gate_needs_both_attempt_jobs(self) -> None:
        gate = job(load_fixture("gate_needs_all_attempt_jobs.yml"), FIXTURE_GATE_JOB)
        assert set(as_list(gate.get("needs"))) == {
            FIXTURE_PRIMARY_JOB,
            FIXTURE_FALLBACK_JOB,
        }

    def test_combined_fixture_gate_needs_review_attempts_job(self) -> None:
        gate = job(load_fixture("combined_attempts_job.yml"), FIXTURE_GATE_JOB)
        assert as_list(gate.get("needs")) == [FIXTURE_COMBINED_ATTEMPTS_JOB]


class TestGateJobNeedsAttemptJobs:
    """Unit coverage for ``tests.ci.review_gate_ordering``."""

    def test_same_job_gate_is_flagged(self) -> None:
        offense = gate_job_needs_attempt_jobs(
            load_fixture("same_job_gate_races_fallback.yml"),
            workflow="same_job_gate_races_fallback.yml",
        )
        assert offense is not None
        assert offense.gate_job == "review"
        assert "review" in offense.missing_needs

    def test_split_jobs_missing_fallback_needs_is_flagged(self) -> None:
        offense = gate_job_needs_attempt_jobs(
            load_fixture("split_attempt_jobs.yml"),
            workflow="split_attempt_jobs.yml",
        )
        assert offense is not None
        assert offense.missing_needs == (FIXTURE_FALLBACK_JOB,)

    def test_gate_needs_all_attempt_jobs_passes(self) -> None:
        offense = gate_job_needs_attempt_jobs(
            load_fixture("gate_needs_all_attempt_jobs.yml"),
            workflow="gate_needs_all_attempt_jobs.yml",
        )
        assert offense is None

    def test_combined_attempts_job_passes(self) -> None:
        offense = gate_job_needs_attempt_jobs(
            load_fixture("combined_attempts_job.yml"),
            workflow="combined_attempts_job.yml",
        )
        assert offense is None


class TestScanWorkflows:
    """Directory scan over installed fixture trees."""

    def test_scan_flags_racing_fixtures(self, tmp_path: Path) -> None:
        _install_hg_fixtures(tmp_path)
        offenses = scan_workflows(tmp_path)
        flagged = {offense.workflow for offense in offenses}
        assert "same_job_gate_races_fallback.yml" in flagged
        assert "split_attempt_jobs.yml" in flagged

    def test_scan_passes_correct_ordering_fixtures(self, tmp_path: Path) -> None:
        workflows = _install_hg_fixtures(tmp_path)
        for name in (
            "same_job_gate_races_fallback.yml",
            "split_attempt_jobs.yml",
        ):
            (workflows / name).unlink()
        offenses = scan_workflows(tmp_path)
        assert offenses == []


class TestMergecraftWorkflow:
    """Integration: the real consumer workflow must satisfy D9 after W14."""

    def test_review_job_still_declares_nous_and_codex_attempts(self) -> None:
        doc = load_workflow(_MERGECRAFT_WORKFLOW)
        assert find_step(doc, NOUS_REVIEW_STEP) is not None
        assert find_step(doc, CODEX_REVIEW_STEP) is not None
        assert find_step(doc, CODEX_FALLBACK_DECIDE_STEP) is not None

    def test_fail_closed_gate_step_still_present(self) -> None:
        doc = load_workflow(_MERGECRAFT_WORKFLOW)
        assert find_step(doc, APPROVAL_GATE_STEP) is not None

    def test_gate_step_still_fails_closed_on_missing_check(self) -> None:
        text = read_text(f".github/workflows/{_MERGECRAFT_WORKFLOW}")
        assert "Failing closed" in text
        assert "mergecraft review incomplete" in text

    def test_mergecraft_yml_gate_waits_for_every_review_attempt(self) -> None:
        offense = gate_job_needs_attempt_jobs(
            load_workflow(_MERGECRAFT_WORKFLOW),
            workflow=_MERGECRAFT_WORKFLOW,
        )
        assert offense is None, f"mergecraft.yml gate ordering: {offense}"

    def test_mergecraft_yml_approval_gate_is_not_in_review_job(self) -> None:
        assert approval_gate_job(load_workflow(_MERGECRAFT_WORKFLOW)) != "review"


class TestRepoWorkflowScan:
    """Scanning the real tree must pass once W14 lands."""

    def test_repo_mergecraft_workflow_passes_gate_ordering_scan(self) -> None:
        offenses = [
            offense
            for offense in scan_workflows(REPO_ROOT)
            if offense.workflow == _MERGECRAFT_WORKFLOW
        ]
        assert offenses == []


__all__ = [
    "TestFixtureAnchors",
    "TestGateJobNeedsAttemptJobs",
    "TestMergecraftWorkflow",
    "TestRepoWorkflowScan",
    "TestScanWorkflows",
]
