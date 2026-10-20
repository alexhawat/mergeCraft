"""``actions/checkout`` persists its token unless a job opts out (#885).

The persisted token sits in ``.git/config`` for every later step and for
anything uploaded from the workspace. A job that never pushes has no use for
it, so every checkout in every workflow sets ``persist-credentials: false``
unless the job later pushes with that credential. The pushing jobs are named
here and each is checked to push, so the exemption cannot outlive the push.
"""

from __future__ import annotations

from typing import Any

import pytest
import yaml

from tests.ci.workflow_support import WORKFLOWS

# (workflow, job id) -> why the checkout credential must stay.
_PUSHING_JOBS: dict[tuple[str, str], str] = {
    ("bump-action-pin.yml", "prepare"): "commits and pushes the pin-bump branch",
    ("release.yml", "prepare"): "Craft pushes the release branch with the checkout credential",
}


def _checkouts() -> list[tuple[str, str, int, dict[str, Any]]]:
    found: list[tuple[str, str, int, dict[str, Any]]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job_id, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            for index, step in enumerate(job.get("steps") or []):
                uses = step.get("uses") if isinstance(step, dict) else None
                if isinstance(uses, str) and uses.startswith("actions/checkout@"):
                    found.append((path.name, job_id, index, step))
    return found


def _persist(step: dict[str, Any]) -> str:
    with_block = step.get("with") or {}
    return str(with_block.get("persist-credentials")).lower()


def test_the_scan_sees_checkouts_in_every_workflow_that_has_one() -> None:
    names = {name for name, _, _, _ in _checkouts()}
    assert {"ci.yml", "ci-cd.yml", "codeql.yml", "docker.yml", "e2e.yml"} <= names
    assert {"findings-carryover.yml", "integration.yml", "release.yml"} <= names


_NON_PUSHING = [row for row in _checkouts() if (row[0], row[1]) not in _PUSHING_JOBS]


@pytest.mark.parametrize(
    ("workflow", "job_id", "index", "step"),
    _NON_PUSHING,
    ids=[f"{workflow}:{job_id}:{index}" for workflow, job_id, index, _ in _NON_PUSHING],
)
def test_a_job_that_never_pushes_does_not_persist_credentials(
    workflow: str, job_id: str, index: int, step: dict[str, Any]
) -> None:
    assert _persist(step) == "false", (
        f"{workflow}:{job_id} step {index}: actions/checkout must set "
        "persist-credentials: false (the job does not push with it)"
    )


@pytest.mark.parametrize(("workflow", "job_id"), sorted(_PUSHING_JOBS))
def test_an_exempt_job_really_pushes(workflow: str, job_id: str) -> None:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    doc = yaml.safe_load(text)
    job = doc["jobs"][job_id]
    permissions = job.get("permissions") or {}
    assert permissions.get("contents") == "write", (
        f"{workflow}:{job_id} is exempt from persist-credentials: false but cannot push"
    )
