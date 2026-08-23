"""Helpers for Batch HG / #433 — approval gate must wait for Codex fallback.

The mergeCraft consumer workflow can post ``mergecraft-approval`` from a Codex
fallback attempt that is still in flight when the fail-closed gate samples the
check-runs API. D9 requires job-level ``needs:`` ordering so the gate cannot
start until every review attempt in that workflow has finished.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tests.ci.workflow_support import as_list, job

# Canonical step names in ``.github/workflows/mergecraft.yml``.
APPROVAL_GATE_STEP = "Fail when mergeCraft would not approve"
CODEX_REVIEW_STEP = "mergeCraft PR review (Codex)"
NOUS_REVIEW_STEP = "mergeCraft PR review (Nous Tencent HY3)"
CODEX_FALLBACK_DECIDE_STEP = "Decide Codex fallback after Nous"

# Fixture job names (``tests/ci/fixtures/workflow_review_gate_hg/``).
FIXTURE_PRIMARY_JOB = "primary-review"
FIXTURE_FALLBACK_JOB = "codex-fallback"
FIXTURE_GATE_JOB = "approval-gate"
FIXTURE_COMBINED_ATTEMPTS_JOB = "review-attempts"


@dataclass(frozen=True, slots=True)
class StepRef:
    """A step located inside a workflow job."""

    job: str
    index: int
    name: str


@dataclass(frozen=True, slots=True)
class GateOrderingOffense:
    """The approval gate can start before a review attempt finishes."""

    workflow: str
    gate_job: str
    missing_needs: tuple[str, ...]
    detail: str

    def __str__(self) -> str:
        missing = ", ".join(self.missing_needs) or "(same job as review attempts)"
        return (
            f"{self.workflow} gate job {self.gate_job!r} missing needs: {missing} — {self.detail}"
        )


def _step_name(step: Any) -> str | None:
    if not isinstance(step, dict):
        return None
    name = step.get("name")
    return name if isinstance(name, str) else None


def find_step(doc: dict[str, Any], step_name: str) -> StepRef | None:
    """Return the first job/step index whose ``name`` matches ``step_name``."""
    jobs = doc.get("jobs") or {}
    if not isinstance(jobs, dict):
        return None
    for job_name, job_def in jobs.items():
        if not isinstance(job_def, dict):
            continue
        steps = job_def.get("steps")
        if not isinstance(steps, list):
            continue
        for index, step in enumerate(steps):
            if _step_name(step) == step_name:
                return StepRef(job=str(job_name), index=index, name=step_name)
    return None


def review_attempt_jobs(doc: dict[str, Any]) -> set[str]:
    """Jobs that can run a mergeCraft review attempt (Nous and/or Codex)."""
    attempts: set[str] = set()
    for step_name in (NOUS_REVIEW_STEP, CODEX_REVIEW_STEP):
        found = find_step(doc, step_name)
        if found is not None:
            attempts.add(found.job)
    return attempts


def approval_gate_job(doc: dict[str, Any]) -> str | None:
    """Job that runs the fail-closed approval gate step, if any."""
    found = find_step(doc, APPROVAL_GATE_STEP)
    return found.job if found is not None else None


def gate_job_needs_attempt_jobs(
    doc: dict[str, Any], *, workflow: str
) -> GateOrderingOffense | None:
    """Return an offense when the gate can race a review attempt (#433 / D9)."""
    gate_job_name = approval_gate_job(doc)
    if gate_job_name is None:
        return GateOrderingOffense(
            workflow=workflow,
            gate_job="(missing)",
            missing_needs=(),
            detail=f"step {APPROVAL_GATE_STEP!r} not found",
        )

    attempt_jobs = review_attempt_jobs(doc)
    if not attempt_jobs:
        return GateOrderingOffense(
            workflow=workflow,
            gate_job=gate_job_name,
            missing_needs=(),
            detail="no review attempt steps found",
        )

    same_job_attempts = attempt_jobs & {gate_job_name}
    if same_job_attempts:
        return GateOrderingOffense(
            workflow=workflow,
            gate_job=gate_job_name,
            missing_needs=tuple(sorted(same_job_attempts)),
            detail=(
                "approval gate shares a job with review attempts — "
                "Codex fallback can post mergecraft-approval after the gate "
                "step would sample check-runs (#433)"
            ),
        )

    gate_def = job(doc, gate_job_name)
    needs = {str(item) for item in as_list(gate_def.get("needs"))}
    missing = tuple(sorted(attempt_jobs - needs))
    if missing:
        return GateOrderingOffense(
            workflow=workflow,
            gate_job=gate_job_name,
            missing_needs=missing,
            detail="gate job must needs: every review attempt job",
        )
    return None


def scan_workflows(root: Path) -> list[GateOrderingOffense]:
    """Scan ``root/.github/workflows`` for approval-gate ordering offenses."""
    workflows_dir = root / ".github" / "workflows"
    offenses: list[GateOrderingOffense] = []
    if not workflows_dir.is_dir():
        return offenses
    for path in sorted(workflows_dir.glob("*.yml")):
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            continue
        offense = gate_job_needs_attempt_jobs(loaded, workflow=path.name)
        if offense is not None:
            offenses.append(offense)
    return offenses


def load_fixture(name: str) -> dict[str, Any]:
    fixtures = Path(__file__).resolve().parent / "fixtures" / "workflow_review_gate_hg"
    path = fixtures / name
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{name} did not parse as a mapping"
    return loaded


__all__ = [
    "APPROVAL_GATE_STEP",
    "CODEX_FALLBACK_DECIDE_STEP",
    "CODEX_REVIEW_STEP",
    "FIXTURE_COMBINED_ATTEMPTS_JOB",
    "FIXTURE_FALLBACK_JOB",
    "FIXTURE_GATE_JOB",
    "FIXTURE_PRIMARY_JOB",
    "NOUS_REVIEW_STEP",
    "GateOrderingOffense",
    "StepRef",
    "approval_gate_job",
    "find_step",
    "gate_job_needs_attempt_jobs",
    "load_fixture",
    "review_attempt_jobs",
    "scan_workflows",
]
