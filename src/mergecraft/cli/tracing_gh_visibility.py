"""Read-only GitHub Action tracing-visibility probe (issue #56 area).

Operators run mergeCraft as a GitHub Action where tracing is driven by Action
**inputs** (``tracing``, ``logfire-token``, ``tracing-to``) → env vars
(``MERGECRAFT_TRACING``, ``LOGFIRE_TOKEN``). A local ``mergecraft config
tracing`` cannot see the Action's runtime env, but it *can* tell the operator
whether tracing would be "enabled for the GitHub Action" by inspecting the
project's workflow file.

This helper is purely static: it finds the workflow file, parses the YAML, and
looks for a mergeCraft action step (``using: docker`` / ``alexhawat/mergecraft``)
whose ``with:`` block sets ``tracing: true`` or passes a non-empty
``logfire-token`` / ``tracing-to``. No network, no GitHub API.

Exports:
    detect_github_action_tracing -- probe the workflow for tracing enablement.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

_MERGECFAFT_IMAGE_HINT = "alexhawat/mergecraft"


def _find_workflow_file(workspace: str | None = None) -> tuple[Path | None, str]:
    """Return ``(path, source)`` for the workflow file to inspect.

    Resolution order:

    1. ``${GITHUB_WORKSPACE:-.github/workflows}/mergecraft.yml`` — the canonical
       self-review workflow name.
    2. Fall back to scanning ``.github/workflows/*.yml`` for a step that uses
       ``docker`` / references the ``alexhawat/mergecraft`` image.

    ``source`` is the discovered path as a string, or ``"not found"``.
    """
    # ``GITHUB_WORKSPACE`` points at the repo root, so the workflow lives under
    # ``$GITHUB_WORKSPACE/.github/workflows``. When no workspace is given (local
    # run) resolve relative to the current working directory instead.
    workflows_dir = (
        Path(workspace) / ".github" / "workflows" if workspace else Path(".github/workflows")
    )
    canonical = workflows_dir / "mergecraft.yml"
    if canonical.is_file():
        return canonical, str(canonical)

    if workflows_dir.is_dir():
        for candidate in sorted(workflows_dir.glob("*.yml")):
            if _has_mergecraft_step(candidate):
                return candidate, str(candidate)
    return None, "not found"


def _has_mergecraft_step(workflow_path: Path) -> bool:
    """True when the workflow has a step using the mergeCraft action."""
    try:
        data = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError):  # fmt: skip
        return False
    return _find_mergecraft_inputs(data) is not None


def _find_mergecraft_inputs(data: Any) -> dict[str, Any] | None:
    """Return the mergeCraft step's ``with:`` map, or ``None``.

    Walks every job → step and returns the first step that either uses
    ``docker`` or references the ``alexhawat/mergecraft`` image.
    """
    if not isinstance(data, dict):
        return None
    jobs = data.get("jobs")
    if not isinstance(jobs, dict):
        return None
    for job in jobs.values():
        if not isinstance(job, dict):
            continue
        steps = job.get("steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, dict):
                continue
            uses = step.get("uses")
            if not isinstance(uses, str):
                continue
            if "docker" in uses.lower() or _MERGECFAFT_IMAGE_HINT in uses.lower():
                with_block = step.get("with")
                return with_block if isinstance(with_block, dict) else {}
    return None


def detect_github_action_tracing(
    workspace: str | None = None,
) -> dict[str, Any]:
    """Probe the project workflow for GitHub-Action tracing enablement.

    Returns a dict:

    - ``github_action_tracing`` (bool) — True when the mergeCraft step sets
      ``tracing: true`` (a literal ``true``) or passes a non-empty
      ``logfire-token`` / ``tracing-to``.
    - ``source`` (str) — the workflow path, or ``"not found"``.
    - ``detail`` (str) — a short human-readable explanation.

    When ``workspace`` is omitted, ``$GITHUB_WORKSPACE`` is used (matching the
    Action's own runtime layout), falling back to the local
    ``.github/workflows`` directory.
    """
    resolved_workspace = workspace if workspace is not None else os.environ.get("GITHUB_WORKSPACE")
    path, source = _find_workflow_file(resolved_workspace)
    if path is None:
        return {
            "github_action_tracing": False,
            "source": "not found",
            "detail": "no mergeCraft workflow file found",
        }

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:  # fmt: skip
        return {
            "github_action_tracing": False,
            "source": source,
            "detail": f"could not parse workflow: {exc}",
        }

    with_block = _find_mergecraft_inputs(data)
    if with_block is None:
        return {
            "github_action_tracing": False,
            "source": source,
            "detail": "no mergeCraft action step found in workflow",
        }

    tracing_raw = with_block.get("tracing")
    logfire_token = with_block.get("logfire-token")
    tracing_to = with_block.get("tracing-to")

    tracing_true = str(tracing_raw).strip().lower() == "true"
    has_token = bool(str(logfire_token or "").strip())
    has_to = bool(str(tracing_to or "").strip())

    enabled = tracing_true or has_token or has_to
    if enabled:
        detail = "workflow enables tracing for the GitHub Action"
    else:
        detail = "workflow step present but tracing inputs not set"

    return {
        "github_action_tracing": enabled,
        "source": source,
        "detail": detail,
    }


__all__ = ["detect_github_action_tracing"]
