#!/usr/bin/env python3
"""Guard: caller jobs must grant every permission a local reusable workflow declares.

GitHub rejects a workflow run before any job starts when a ``uses:`` job calls a
reusable workflow that requests more ``permissions`` than the caller holds. The
failure mode is ``startup_failure`` with no logs, annotations, or check runs
(#425). ``actionlint`` cannot see the relationship across two workflow files.

This script scans ``.github/workflows/`` and fails when a job-level ``uses:``
target is a *local* reusable workflow (``./…`` under this repo) whose declared
``permissions`` are not satisfied by the caller job's effective scopes (job
``permissions`` when present, otherwise workflow-level ``permissions``). Scalar
workflow permissions such as ``read-all`` / ``write-all`` are expanded to their
GitHub shorthand meaning before comparison.

Third-party reusable workflows (``owner/repo/.github/workflows/…@ref``) and
composite/action ``uses:`` at the *step* level are out of scope.

Module: scripts.check_called_workflow_permissions
Depends: pathlib, sys, typing, yaml

Exports:
    Offense — one under-permissioned ``uses:`` job
    scan_workflows — return every offense under ``root``
    main — CLI entry; scans ``REPO`` and prints offenses to stderr
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from workflow_yaml import (  # noqa: E402
    load_workflow_file,
    missing_permissions,
    permission_dict,
)

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Offense:
    """One caller job that cannot satisfy its local reusable workflow."""

    workflow: str
    job: str
    missing: dict[str, str]

    def __str__(self) -> str:
        missing = ", ".join(f"{scope}: {level}" for scope, level in sorted(self.missing.items()))
        return f"{self.workflow} job {self.job!r} missing permissions: {missing}"


def _resolve_local_workflow_uses(uses: str, workflows_dir: Path, repo_root: Path) -> Path | None:
    spec = uses.split("@", 1)[0]
    if not spec.startswith("./"):
        return None
    relative = spec.removeprefix("./")
    if relative.startswith(".github/workflows/"):
        return repo_root / relative
    return workflows_dir / relative


def _scan_workflow_file(
    workflow_path: Path,
    workflows_dir: Path,
    repo_root: Path,
) -> list[Offense]:
    doc = load_workflow_file(workflow_path)
    if doc is None:
        return []

    workflow_permissions = permission_dict(doc.get("permissions"))
    jobs = doc.get("jobs")
    if not isinstance(jobs, dict):
        return []

    offenses: list[Offense] = []
    workflow_label = workflow_path.resolve().relative_to(repo_root.resolve()).as_posix()

    for job_name, job in jobs.items():
        if not isinstance(job, dict):
            continue
        uses = job.get("uses")
        if not isinstance(uses, str):
            continue

        callee_path = _resolve_local_workflow_uses(uses, workflows_dir, repo_root)
        if callee_path is None or not callee_path.is_file():
            continue

        callee_doc = load_workflow_file(callee_path)
        if callee_doc is None:
            continue

        callee_permissions = permission_dict(callee_doc.get("permissions"))
        if not callee_permissions:
            continue

        if "permissions" in job:
            caller_permissions = permission_dict(job.get("permissions"))
        else:
            caller_permissions = dict(workflow_permissions)

        missing = missing_permissions(caller_permissions, callee_permissions)
        if missing:
            offenses.append(
                Offense(
                    workflow=workflow_label,
                    job=str(job_name),
                    missing=missing,
                )
            )

    return offenses


def scan_workflows(root: Path | None = None) -> list[Offense]:
    resolved_root = root if root is not None else REPO
    workflows_dir = resolved_root / ".github" / "workflows"
    offenses: list[Offense] = []
    for workflow_path in sorted(workflows_dir.glob("*.yml")):
        offenses.extend(_scan_workflow_file(workflow_path, workflows_dir, resolved_root))
    return offenses


def main() -> int:
    offenses = scan_workflows()
    if not offenses:
        return 0
    for offense in offenses:
        print(offense, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
