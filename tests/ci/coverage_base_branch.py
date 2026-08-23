"""Helpers for Batch HI / #432 — base-branch coverage gate + merge ref measurement.

#432's failure mode: per-PR gates score the head branch, combinations can slip
under the floor on merge, and nothing re-measures ``pre-0.0.1`` / ``main`` with
actionable delta-vs-base reporting. D6 locks push gating, merge-ref preference,
and inherited-vs-caused attribution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.ci.workflow_support import as_list, workflow_on

TARGET_PUSH_BRANCHES = frozenset({"main", "pre-0.0.1"})
COVERAGE_GATE_FRAGMENTS = (
    "make coverage-gate",
    "coverage-gate",
    # mergeCraft ``make ci`` always includes ``coverage-gate`` (see Makefile CI_STEPS).
    "make ci",
)
MERGE_REF_MARKERS = ("refs/pull/", "merge_commit_sha")
DELTA_MARKERS = (
    "delta",
    "vs base",
    "against base",
    "base branch",
    "inherited",
    "check_coverage_delta",
    "--base",
)


@dataclass(frozen=True, slots=True)
class PushCoverageOffense:
    """A protected branch push is not gated by coverage in this workflow."""

    workflow: str
    branch: str
    detail: str

    def __str__(self) -> str:
        return f"{self.workflow} push {self.branch!r}: {self.detail}"


@dataclass(frozen=True, slots=True)
class MergeRefOffense:
    """PR coverage measures head, not the merge result."""

    workflow: str
    job: str
    detail: str

    def __str__(self) -> str:
        return f"{self.workflow} job {self.job!r}: {self.detail}"


@dataclass(frozen=True, slots=True)
class DeltaReportOffense:
    """Coverage gate omits delta-vs-base attribution."""

    workflow: str
    detail: str

    def __str__(self) -> str:
        return f"{self.workflow}: {self.detail}"


def _job_steps_text(job_def: dict[str, Any]) -> str:
    steps = job_def.get("steps")
    if not isinstance(steps, list):
        return ""
    parts: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        run = step.get("run")
        if isinstance(run, str):
            parts.append(run)
        name = step.get("name")
        if isinstance(name, str):
            parts.append(name)
        uses = step.get("uses")
        if isinstance(uses, str):
            parts.append(uses)
        with_block = step.get("with")
        if isinstance(with_block, dict):
            for value in with_block.values():
                if isinstance(value, str):
                    parts.append(value)
    return "\n".join(parts)


def job_runs_coverage_gate(job_def: dict[str, Any]) -> bool:
    """Return whether a job invokes the coverage gate (make target or script)."""
    text = _job_steps_text(job_def)
    return any(fragment in text for fragment in COVERAGE_GATE_FRAGMENTS)


def push_trigger_branches(doc: dict[str, Any]) -> set[str]:
    """Return literal branch names from ``on.push.branches``."""
    on_block = workflow_on(doc)
    if not isinstance(on_block, dict):
        return set()
    push = on_block.get("push")
    if not isinstance(push, dict):
        return set()
    return {str(branch) for branch in as_list(push.get("branches"))}


def workflow_push_runs_coverage_gate(doc: dict[str, Any]) -> bool:
    """Return whether any job in ``doc`` runs coverage-gate."""
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return False
    return any(
        isinstance(job_def, dict) and job_runs_coverage_gate(job_def) for job_def in jobs.values()
    )


def push_coverage_gate_offenses(doc: dict[str, Any], *, workflow: str) -> list[PushCoverageOffense]:
    """Return offenses when push triggers lack a coverage-gate job."""
    branches = push_trigger_branches(doc)
    targets = TARGET_PUSH_BRANCHES & branches
    if not targets:
        return []
    if workflow_push_runs_coverage_gate(doc):
        return []
    return [
        PushCoverageOffense(
            workflow=workflow,
            branch=branch,
            detail="workflow triggers on push but no job runs coverage-gate",
        )
        for branch in sorted(targets)
    ]


def branches_with_push_coverage_gate(root: Path) -> set[str]:
    """Branches that have at least one workflow gating coverage on push."""
    workflows_dir = root / ".github" / "workflows"
    covered: set[str] = set()
    if not workflows_dir.is_dir():
        return covered
    for path in sorted(workflows_dir.glob("*.yml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        if not workflow_push_runs_coverage_gate(loaded):
            continue
        covered |= TARGET_PUSH_BRANCHES & push_trigger_branches(loaded)
    return covered


def missing_push_coverage_branches(root: Path) -> list[str]:
    """Protected branches with no push-triggered coverage gate in any workflow."""
    return sorted(TARGET_PUSH_BRANCHES - branches_with_push_coverage_gate(root))


def checkout_uses_merge_ref(job_def: dict[str, Any]) -> bool:
    """Return whether a checkout step targets the PR merge ref."""
    steps = job_def.get("steps")
    if not isinstance(steps, list):
        return False
    for step in steps:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if not isinstance(uses, str) or "checkout" not in uses.lower():
            continue
        with_block = step.get("with")
        if not isinstance(with_block, dict):
            continue
        ref = with_block.get("ref")
        if not isinstance(ref, str):
            continue
        ref_lower = ref.lower()
        if any(marker in ref_lower for marker in MERGE_REF_MARKERS):
            if "refs/pull" in ref_lower and "merge" in ref_lower:
                return True
            if "merge_commit_sha" in ref_lower:
                return True
    return False


def pr_coverage_merge_ref_offense(doc: dict[str, Any], *, workflow: str) -> MergeRefOffense | None:
    """Return an offense when PR coverage-gate does not checkout the merge ref."""
    on_block = workflow_on(doc)
    if not isinstance(on_block, dict) or "pull_request" not in on_block:
        return None
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return None

    coverage_jobs: list[str] = []
    for job_name, job_def in jobs.items():
        if isinstance(job_def, dict) and job_runs_coverage_gate(job_def):
            coverage_jobs.append(str(job_name))

    if not coverage_jobs:
        return MergeRefOffense(
            workflow=workflow,
            job="(missing)",
            detail="no job runs coverage-gate on pull_request",
        )

    for job_name in coverage_jobs:
        job_def = jobs[job_name]
        if isinstance(job_def, dict) and checkout_uses_merge_ref(job_def):
            return None

    return MergeRefOffense(
        workflow=workflow,
        job=coverage_jobs[0],
        detail="PR coverage-gate job does not checkout refs/pull/N/merge",
    )


def coverage_delta_report_offense(
    doc: dict[str, Any], *, workflow: str
) -> DeltaReportOffense | None:
    """Return an offense when coverage-gate jobs omit delta-vs-base reporting."""
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return DeltaReportOffense(workflow=workflow, detail="workflow has no jobs")

    for job_def in jobs.values():
        if not isinstance(job_def, dict) or not job_runs_coverage_gate(job_def):
            continue
        text = _job_steps_text(job_def).lower()
        if any(marker in text for marker in DELTA_MARKERS):
            return None

    if not any(
        isinstance(job_def, dict) and job_runs_coverage_gate(job_def) for job_def in jobs.values()
    ):
        return DeltaReportOffense(
            workflow=workflow,
            detail="no coverage-gate job to inspect for delta reporting",
        )

    return DeltaReportOffense(
        workflow=workflow,
        detail="coverage-gate job does not report delta vs base branch",
    )


def scan_workflows(root: Path) -> list[PushCoverageOffense]:
    """Scan ``root/.github/workflows`` for per-workflow push coverage offenses."""
    workflows_dir = root / ".github" / "workflows"
    offenses: list[PushCoverageOffense] = []
    if not workflows_dir.is_dir():
        return offenses
    for path in sorted(workflows_dir.glob("*.yml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        offenses.extend(push_coverage_gate_offenses(loaded, workflow=path.name))
    return offenses


def load_fixture(name: str) -> dict[str, Any]:
    fixtures = Path(__file__).resolve().parent / "fixtures" / "workflow_coverage_hi"
    path = fixtures / name
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{name} did not parse as a mapping"
    return loaded


__all__ = [
    "DeltaReportOffense",
    "MergeRefOffense",
    "PushCoverageOffense",
    "branches_with_push_coverage_gate",
    "checkout_uses_merge_ref",
    "coverage_delta_report_offense",
    "job_runs_coverage_gate",
    "load_fixture",
    "missing_push_coverage_branches",
    "pr_coverage_merge_ref_offense",
    "push_coverage_gate_offenses",
    "push_trigger_branches",
    "scan_workflows",
    "workflow_push_runs_coverage_gate",
]
