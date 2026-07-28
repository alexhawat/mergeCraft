"""Execution-mode resolution for catalog analyzers (D4, D5)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mergecraft.analyzers.detect import _eslint_command_prefix, resolve_repo_tool

if TYPE_CHECKING:
    from mergecraft.analyzers.manifest import AnalyzerManifest

_CATALOG_DIR = Path(__file__).resolve().parent / "catalog"
_CATALOG_PREFIX = "@catalog:"
FILES_TOKEN = "{files}"
TRUFFLEHOG_CONFIG_TOKEN = "{trufflehog_config}"

ExecutionMode = Literal["repo-native", "ci-result", "managed", "container", "skip"]

_TYPE_CHECKER_IDS = frozenset({"mypy", "pyright", "basedpyright"})


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
    config_note: str | None = None
    reason: str | None = None


def _repo_tool_binary(manifest: AnalyzerManifest) -> str:
    return manifest.command[0]


def _format_version_note(
    manifest: AnalyzerManifest,
    *,
    repo_tool_version: str | None,
    config_note: str | None,
) -> str | None:
    if not repo_tool_version:
        return None
    parts = [f"ran repo-native {manifest.id} ({repo_tool_version})"]
    if config_note:
        parts.append(f"config: {config_note}")
    return "; ".join(parts)


def detect_repo_tool(
    manifest: AnalyzerManifest, repo_root: Path
) -> tuple[bool, str | None, str | None]:
    """Reuse prep-style PATH detection for repo-native execution (D4)."""
    resolution, skip_reason = resolve_repo_tool(
        manifest.id,
        repo_root=repo_root,
        command_binary=_repo_tool_binary(manifest),
    )
    if resolution is None:
        return False, None, None
    _ = skip_reason
    return True, resolution.path, resolution.version


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
    config_note: str | None = None
    if repo_has_tool is None:
        resolution, skip_reason = resolve_repo_tool(
            manifest.id,
            repo_root=repo_root,
            command_binary=_repo_tool_binary(manifest),
        )
        if resolution is None:
            if manifest.id in _TYPE_CHECKER_IDS:
                return AnalyzerPlan(
                    manifest_id=manifest.id,
                    mode="skip",
                    reason=skip_reason,
                )
            if (
                manifest.runtime == "repo-native"
                and skip_reason
                and skip_reason.startswith("skipped")
            ):
                return AnalyzerPlan(
                    manifest_id=manifest.id,
                    mode="skip",
                    reason=skip_reason,
                )
            repo_has_tool = False
        else:
            repo_has_tool = True
            repo_tool_path = repo_tool_path or resolution.path
            repo_tool_version = repo_tool_version or resolution.version
            config_note = resolution.config_note

    if repo_has_tool:
        argv = tuple(manifest.command)
        if manifest.id == "eslint":
            prefix = _eslint_command_prefix(repo_root)
            if len(prefix) == 2:
                argv = (*prefix, *manifest.command[1:])
            elif len(prefix) == 1:
                argv = (prefix[0], *manifest.command[1:])
        elif repo_tool_path and argv and argv[0] == _repo_tool_binary(manifest):
            argv = (repo_tool_path, *argv[1:])
        version_note = _format_version_note(
            manifest,
            repo_tool_version=repo_tool_version,
            config_note=config_note,
        )
        return AnalyzerPlan(
            manifest_id=manifest.id,
            mode="repo-native",
            argv=argv,
            cwd=repo_root,
            timeout_s=manifest.timeout_s,
            version_note=version_note,
            config_note=config_note,
        )

    if manifest.id in _TYPE_CHECKER_IDS:
        return AnalyzerPlan(
            manifest_id=manifest.id,
            mode="skip",
            reason=(
                f"skipped {manifest.id}: type checker not installed in the repo environment "
                "(repo-native only — managed substitute forbidden, C3/D5)"
            ),
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


def expand_analyzer_argv(
    argv: tuple[str, ...] | list[str],
    *,
    repo_root: Path,
    changed_files: list[str],
) -> tuple[str, ...]:
    """Expand ``{files}`` and ``@catalog:`` tokens in a manifest command."""
    repo_root = repo_root.resolve()
    expanded: list[str] = []
    for arg in argv:
        if arg == FILES_TOKEN:
            for rel in changed_files:
                path = Path(rel)
                candidate = path if path.is_absolute() else repo_root / rel
                try:
                    candidate.resolve().relative_to(repo_root)
                except ValueError:
                    continue
                expanded.append(str(candidate))
            continue
        if arg == TRUFFLEHOG_CONFIG_TOKEN:
            expanded.append(str(_CATALOG_DIR / "trufflehog-detectors.txt"))
            continue
        if arg.startswith(_CATALOG_PREFIX):
            template_path = _CATALOG_DIR / arg.removeprefix(_CATALOG_PREFIX)
            expanded.append(template_path.read_text(encoding="utf-8"))
            continue
        expanded.append(arg)
    return tuple(expanded)


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
    "FILES_TOKEN",
    "TRUFFLEHOG_CONFIG_TOKEN",
    "AnalyzerPlan",
    "ExecutionMode",
    "detect_repo_tool",
    "expand_analyzer_argv",
    "resolve_analyzer",
    "static_check_plan",
]
