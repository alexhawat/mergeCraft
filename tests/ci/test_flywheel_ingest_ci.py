"""R5 structural guard — flywheel ingest adds no required PR check (R-D10).

Wave plan: the verification/evals/receipts wave plan (R5). Test-plan doc:
``docs/test-plans/30-verification-evals-receipts.md``.

#738 says ingested cases participate in the **keyless** ``eval replay-bank`` /
``eval-gate`` path as structural cases only, and the wave plan pins that the
ingest adds **no new required PR check** (R-D10). The structural gate already
exists: ``eval-gate`` replays ``evals/cases`` and compares against the
committed baseline. The ingest writes into that same bank, so no new job is
needed.

This guard is green by design: it fails if a later change promotes flywheel
ingest into a blocking workflow job, or if the existing structural gate stops
replaying the bank the ingest writes.
"""

from __future__ import annotations

from typing import Any

import yaml

from tests.ci.workflow_support import WORKFLOWS, load_workflow
from tests.evals.support_eval_calibration import (
    EVAL_GATE_JOB_ID,
    PROVIDER_SECRET_ENV,
    job_script_text,
)


def _flywheel_jobs() -> list[tuple[str, str, dict[str, Any]]]:
    """Every workflow job whose id, name, or script names flywheel ingest."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = load_workflow(path.name).get("jobs") or {}
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            blob = f"{job_id}\n{job.get('name') or ''}\n{job_script_text(job)}".casefold()
            if "flywheel" in blob or "eval ingest" in blob or "eval-ingest" in blob:
                found.append((path.name, str(job_id), job))
    return found


def test_no_workflow_job_runs_flywheel_ingest_as_a_blocking_check() -> None:
    """R-D10 — if an ingest job exists at all, it is advisory and keyless."""
    for workflow_name, job_id, job in _flywheel_jobs():
        assert job.get("continue-on-error") is True, (
            f"{workflow_name}:{job_id} must not become a required PR check (R-D10)"
        )
        env = job.get("env") or {}
        assert PROVIDER_SECRET_ENV.isdisjoint(set(env)), (
            f"{workflow_name}:{job_id} must stay keyless"
        )
        assert "secrets." not in yaml.safe_dump(job), (
            f"{workflow_name}:{job_id} must not read repository secrets"
        )


def test_existing_structural_eval_gate_still_replays_the_bank() -> None:
    """The required structural gate is unchanged and still reads the bank."""
    jobs = load_workflow("ci.yml").get("jobs") or {}
    assert EVAL_GATE_JOB_ID in jobs, "eval-gate was removed from ci.yml (R-D10 regression)"
    gate = jobs[EVAL_GATE_JOB_ID]
    assert isinstance(gate, dict)
    assert gate.get("continue-on-error") in (None, False), "eval-gate stays the required check"
    text = job_script_text(gate).casefold()
    assert "replay-bank" in text or "eval-replay" in text
    assert "eval gate" in text or "eval-gate" in text
