"""A reusable workflow called from another repository must not get every secret.

`secrets: inherit` hands the caller's whole secret set to the called workflow.
GitHub already grants a called workflow `github.token` / `secrets.GITHUB_TOKEN`,
so a third-party preview that reads nothing else must receive an explicit — and
empty — mapping instead.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from tests.ci.workflow_support import WORKFLOWS


def _external_calls(doc: dict[str, Any], *, source: str) -> list[tuple[str, dict[str, Any]]]:
    """Return ``(job_name, job)`` pairs whose job calls an external workflow."""
    jobs = doc.get("jobs") or {}
    assert isinstance(jobs, dict), f"{source}: jobs is not a mapping"
    found: list[tuple[str, dict[str, Any]]] = []
    for name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        uses = job.get("uses")
        if isinstance(uses, str) and "@" in uses and not uses.startswith("./"):
            found.append((str(name), job))
    return found


def _workflow_files() -> list[Path]:
    return sorted(WORKFLOWS.glob("*.yml"))


def test_no_external_reusable_workflow_receives_every_secret() -> None:
    offenders: list[str] = []
    for path in _workflow_files():
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            continue
        for job_name, job in _external_calls(doc, source=path.name):
            if job.get("secrets") == "inherit":
                offenders.append(f"{path.name}:{job_name}")
    assert not offenders, (
        "these jobs hand every repository secret to a workflow outside this "
        f"repository: {offenders}; pass only what the callee needs"
    )
