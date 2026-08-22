#!/usr/bin/env python3
"""Guard: caller jobs must grant every permission a local reusable workflow declares.

GitHub rejects a workflow run before any job starts when a ``uses:`` job calls a
reusable workflow that requests more ``permissions`` than the caller holds. The
failure mode is ``startup_failure`` with no logs, annotations, or check runs
(#425). ``actionlint`` cannot see the relationship across two workflow files.

This script scans ``.github/workflows/`` and fails when a job-level ``uses:``
target is a *local* reusable workflow (``./…`` under this repo) whose declared
``permissions`` are not satisfied by the caller job's effective scopes (job
``permissions`` when present, otherwise workflow-level ``permissions``).

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
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]

_PERMISSION_RANK = {
    "none": 0,
    "read": 1,
    "write": 2,
}


class Offense:
    """One caller job that cannot satisfy its local reusable workflow."""

    __slots__ = ("job", "missing", "workflow")

    def __init__(self, *, workflow: str, job: str, missing: dict[str, str]) -> None:
        self.workflow = workflow
        self.job = job
        self.missing = missing

    def __str__(self) -> str:
        missing = ", ".join(f"{scope}: {level}" for scope, level in sorted(self.missing.items()))
        return f"{self.workflow} job {self.job!r} missing permissions: {missing}"


def _permission_dict(raw: Any) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in raw.items():
        if isinstance(key, str) and isinstance(value, str):
            out[key] = value
    return out


def _level_satisfies(have: str | None, need: str) -> bool:
    if have is None:
        return False
    have_rank = _PERMISSION_RANK.get(have, -1)
    need_rank = _PERMISSION_RANK.get(need, -1)
    if need_rank < 0:
        return have == need
    return have_rank >= need_rank


def _missing_permissions(
    caller: dict[str, str],
    callee: dict[str, str],
) -> dict[str, str]:
    missing: dict[str, str] = {}
    for scope, need in callee.items():
        if not _level_satisfies(caller.get(scope), need):
            missing[scope] = need
    return missing


def _resolve_local_workflow_uses(uses: str, workflows_dir: Path, repo_root: Path) -> Path | None:
    spec = uses.split("@", 1)[0]
    if not spec.startswith("./"):
        return None
    relative = spec.removeprefix("./")
    if relative.startswith(".github/workflows/"):
        return repo_root / relative
    return workflows_dir / relative


def _load_workflow(path: Path) -> dict[str, Any] | None:
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError:
        return None
    if not isinstance(loaded, dict):
        return None
    return loaded


def _scan_workflow_file(
    workflow_path: Path,
    workflows_dir: Path,
    repo_root: Path,
) -> list[Offense]:
    doc = _load_workflow(workflow_path)
    if doc is None:
        return []

    workflow_permissions = _permission_dict(doc.get("permissions"))
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

        callee_doc = _load_workflow(callee_path)
        if callee_doc is None:
            continue

        callee_permissions = _permission_dict(callee_doc.get("permissions"))
        if not callee_permissions:
            continue

        if "permissions" in job:
            caller_permissions = _permission_dict(job.get("permissions"))
        else:
            caller_permissions = dict(workflow_permissions)

        missing = _missing_permissions(caller_permissions, callee_permissions)
        if missing:
            offenses.append(
                Offense(
                    workflow=workflow_label,
                    job=str(job_name),
                    missing=missing,
                )
            )

    return offenses


def scan_workflows(root: Path) -> list[Offense]:
    """Return every under-permissioned local ``uses:`` job under ``root``."""
    repo_root = root.resolve()
    workflows_dir = repo_root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return []

    offenses: list[Offense] = []
    for workflow_path in sorted(workflows_dir.glob("*.yml")) + sorted(workflows_dir.glob("*.yaml")):
        offenses.extend(_scan_workflow_file(workflow_path, workflows_dir, repo_root))
    return offenses


def main() -> int:
    """Scan ``REPO`` and fail when a local reusable-workflow caller lacks permissions."""
    offenses = scan_workflows(REPO)
    if not offenses:
        return 0

    print(
        "caller job permissions must satisfy every local reusable workflow they invoke (see #425):",
        file=sys.stderr,
    )
    for offense in offenses:
        print(f"  {offense}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
