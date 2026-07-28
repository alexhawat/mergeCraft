"""Execution-mode resolution for catalog analyzers (D4, D5)."""

from __future__ import annotations

import shlex
import shutil
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

ExecutionMode = Literal["repo-native", "ci-result", "managed", "container", "skip"]


@dataclass(frozen=True, slots=True)
class AnalyzerPlan:
    """Resolved execution plan for one analyzer."""

    manifest_id: str
    mode: ExecutionMode
    argv: tuple[str, ...] = ()
    cwd: Path | None = None
    env: dict[str, str] = field(default_factory=dict)
    timeout_s: int = 300
    version_note: str | None = None
    reason: str | None = None


def _repo_tool_binary(manifest: AnalyzerManifest) -> str:
    return manifest.command[0]


def detect_repo_tool(
    manifest: AnalyzerManifest, repo_root: Path
) -> tuple[bool, str | None, str | None]:
    """Reuse prep-style PATH detection for repo-native execution (D4)."""
    _ = repo_root
    binary = _repo_tool_binary(manifest)
    path = shutil.which(binary)
    if path is None:
        return False, None, None
    version: str | None = None
    try:
        import subprocess

        completed = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if completed.stdout.strip():
            version = completed.stdout.strip().splitlines()[0]
    except OSError:
        version = None
    return True, path, version


def resolve_analyzer(
    *,
    manifest: AnalyzerManifest,
    repo_root: Path,
    repo_has_tool: bool | None = None,
    ci_artifact_available: bool = False,
    managed_available: bool = False,
    container_available: bool = False,
    repo_tool_path: str | None = None,
    repo_tool_version: str | None = None,
    managed_version: str | None = None,
) -> AnalyzerPlan:
    """Resolve D4's preference chain for one manifest."""
    if repo_has_tool is None:
        has_tool, detected_path, detected_version = detect_repo_tool(manifest, repo_root)
        repo_has_tool = has_tool
        repo_tool_path = repo_tool_path or detected_path
        repo_tool_version = repo_tool_version or detected_version

    if repo_has_tool:
        argv = tuple(manifest.command)
        if repo_tool_path and argv and argv[0] == _repo_tool_binary(manifest):
            argv = (repo_tool_path, *argv[1:])
        version_note = None
        if repo_tool_version:
            version_note = f"ran repo-native {manifest.id} ({repo_tool_version})"
        return AnalyzerPlan(
            manifest_id=manifest.id,
            mode="repo-native",
            argv=argv,
            cwd=repo_root,
            timeout_s=manifest.timeout_s,
            version_note=version_note,
        )

    if ci_artifact_available:
        return AnalyzerPlan(
            manifest_id=manifest.id,
            mode="ci-result",
            cwd=repo_root,
            timeout_s=manifest.timeout_s,
        )

    if managed_available and manifest.runtime in {"managed", "repo-native"}:
        version = managed_version or manifest.version
        version_note = f"ran mergeCraft's pinned {manifest.id} {version}; your repo pins none"
        return AnalyzerPlan(
            manifest_id=manifest.id,
            mode="managed",
            argv=tuple(manifest.command),
            cwd=repo_root,
            timeout_s=manifest.timeout_s,
            version_note=version_note,
        )

    if container_available and manifest.runtime == "container":
        return AnalyzerPlan(
            manifest_id=manifest.id,
            mode="container",
            argv=tuple(manifest.command),
            cwd=repo_root,
            timeout_s=manifest.timeout_s,
        )

    return AnalyzerPlan(
        manifest_id=manifest.id,
        mode="skip",
        reason=(
            f"skipped {manifest.id}: no repo-native tool, CI artifact, managed binary, "
            "or container runtime available"
        ),
    )


def static_check_plan(
    *,
    name: str,
    command: str,
    root: Path,
    changed_files: list[str] | None = None,
) -> AnalyzerPlan:
    """Build a manifest-less plan for declared ``staticChecks`` gates."""
    from mergecraft.review_checks import FILES_TOKEN

    files = changed_files or []
    argv = shlex.split(command)
    if FILES_TOKEN in argv:
        index = argv.index(FILES_TOKEN)
        argv = [*argv[:index], *files, *argv[index + 1 :]]
    return AnalyzerPlan(
        manifest_id=name,
        mode="repo-native",
        argv=tuple(argv),
        cwd=root,
    )


__all__ = [
    "AnalyzerPlan",
    "ExecutionMode",
    "detect_repo_tool",
    "resolve_analyzer",
    "static_check_plan",
]
