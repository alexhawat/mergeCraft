"""R4 RED suite — the shadow-comparison CI job is optional and keyless (R-D10).

Wave plan: the verification/evals/receipts wave plan (R4). Test-plan doc:
``docs/test-plans/30-verification-evals-receipts.md``.

The shadow corpus report ships as an **optional, keyless** workflow job: it
publishes rows a run already recorded, and it must never become a required PR
blocker. ``continue-on-error: true`` is the repo's
established non-blocking mechanism (``mutation-advisory``); a job that needs a
provider key is a job that gets disabled.

The R4 implementation wave (``bbb1e3aa``) landed the job; the reconciliation
run (``f8c575d3-5a2f-433a-9e6a-8c978fcd25d9``) removed the non-strict ``xfail``
marker so this is a real pass.
"""

from __future__ import annotations

from typing import Any

import yaml

from tests.ci.workflow_support import WORKFLOWS, load_workflow
from tests.evals.support_eval_calibration import PROVIDER_SECRET_ENV


def _shadow_jobs() -> list[tuple[str, str, dict[str, Any]]]:
    """Every workflow job whose id names a shadow comparison."""
    found: list[tuple[str, str, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        jobs = load_workflow(path.name).get("jobs") or {}
        for job_id, job in jobs.items():
            if not isinstance(job, dict):
                continue
            if "shadow" in str(job_id).casefold():
                found.append((path.name, str(job_id), job))
    return found


def test_shadow_comparison_job_is_non_blocking_and_keyless() -> None:
    """The shadow-comparison job is advisory and needs no provider credential."""
    jobs = _shadow_jobs()
    assert jobs, "no shadow-comparison job found in .github/workflows"
    for workflow_name, job_id, job in jobs:
        assert job.get("continue-on-error") is True, (
            f"{workflow_name}:{job_id} must be non-blocking (continue-on-error: true) — R-D10"
        )
        env = job.get("env") or {}
        assert PROVIDER_SECRET_ENV.isdisjoint(set(env)), f"{workflow_name}:{job_id} must be keyless"
        assert "secrets." not in yaml.safe_dump(job), (
            f"{workflow_name}:{job_id} must not read repository secrets"
        )
