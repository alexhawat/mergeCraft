"""Execution-mode resolution for catalog analyzers (D4, D5)."""

from __future__ import annotations

import shlex
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from mergecraft.analyzers.detect import _eslint_command_prefix, resolve_repo_tool

if TYPE_CHECKING:
    from collections.abc import Callable

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


def _declared_unavailable_plan(manifest: AnalyzerManifest) -> AnalyzerPlan | None:
    """Per-source resolver: a manifest the catalog itself marks unavailable."""
    if not manifest.declared_unavailable:
        return None
    return AnalyzerPlan(
        manifest_id=manifest.id,
        mode="skip",
        reason=f"skipped {manifest.id}: {manifest.declared_unavailable}",
    )


def _agentsec_plan(manifest: AnalyzerManifest, repo_root: Path) -> AnalyzerPlan | None:
    """Per-source resolver: the ``agentsec`` special-case (mergeCraft's native engine)."""
    if manifest.id != "agentsec":
        return None
    return AnalyzerPlan(
        manifest_id=manifest.id,
        mode="repo-native",
        argv=("agentsec",),
        cwd=repo_root,
        timeout_s=manifest.timeout_s,
        version_note="ran mergeCraft native agent-security policy engine",
        config_note="native YAML rules",
    )


@dataclass(frozen=True, slots=True)
class _RepoToolState:
    """Availability + provenance for the repo-native execution source."""

    available: bool
    tool_path: str | None
    tool_version: str | None
    config_note: str | None


def _detect_repo_tool_state(
    manifest: AnalyzerManifest,
    repo_root: Path,
    *,
    repo_has_tool: bool | None,
    repo_tool_path: str | None,
    repo_tool_version: str | None,
) -> tuple[_RepoToolState, AnalyzerPlan | None]:
    """Resolve repo-native tool availability, or an early skip plan on detection failure.

    Detection only runs when the caller left ``repo_has_tool`` unresolved
    (``None``) — the "figure it out" default. An explicit caller-supplied
    boolean (including ``allow_repo_binaries=False`` forcing it to
    ``False``) skips detection entirely and is trusted as-is. On a failed
    detection, type checkers and repo-native-only manifests skip
    immediately with ``resolve_repo_tool``'s own reason — a distinct
    message from the generic type-checker skip later in the ladder.
    """
    if repo_has_tool is not None:
        return _RepoToolState(repo_has_tool, repo_tool_path, repo_tool_version, None), None

    resolution, skip_reason = resolve_repo_tool(
        manifest.id,
        repo_root=repo_root,
        command_binary=_repo_tool_binary(manifest),
    )
    if resolution is None:
        if manifest.id in _TYPE_CHECKER_IDS:
            return (
                _RepoToolState(False, None, None, None),
                AnalyzerPlan(manifest_id=manifest.id, mode="skip", reason=skip_reason),
            )
        if manifest.runtime == "repo-native" and skip_reason and skip_reason.startswith("skipped"):
            return (
                _RepoToolState(False, None, None, None),
                AnalyzerPlan(manifest_id=manifest.id, mode="skip", reason=skip_reason),
            )
        return _RepoToolState(False, None, None, None), None

    return (
        _RepoToolState(
            True,
            repo_tool_path or resolution.path,
            repo_tool_version or resolution.version,
            resolution.config_note,
        ),
        None,
    )


def _repo_native_plan(
    manifest: AnalyzerManifest, repo_root: Path, state: _RepoToolState
) -> AnalyzerPlan | None:
    """Per-source resolver: the repo's own binary, once availability is known."""
    if not state.available:
        return None
    argv = tuple(manifest.command)
    if manifest.id == "eslint":
        prefix = _eslint_command_prefix(repo_root)
        if len(prefix) == 2:
            argv = (*prefix, *manifest.command[1:])
        elif len(prefix) == 1:
            argv = (prefix[0], *manifest.command[1:])
    elif state.tool_path and argv and argv[0] == _repo_tool_binary(manifest):
        argv = (state.tool_path, *argv[1:])
    version_note = _format_version_note(
        manifest, repo_tool_version=state.tool_version, config_note=state.config_note
    )
    return AnalyzerPlan(
        manifest_id=manifest.id,
        mode="repo-native",
        argv=argv,
        cwd=repo_root,
        timeout_s=manifest.timeout_s,
        version_note=version_note,
        config_note=state.config_note,
    )


def _type_checker_missing_plan(manifest: AnalyzerManifest) -> AnalyzerPlan | None:
    """Per-source resolver: type checkers are repo-native only (C3/D5) — no substitute."""
    if manifest.id not in _TYPE_CHECKER_IDS:
        return None
    return AnalyzerPlan(
        manifest_id=manifest.id,
        mode="skip",
        reason=(
            f"skipped {manifest.id}: type checker not installed in the repo environment "
            "(repo-native only — managed substitute forbidden, C3/D5)"
        ),
    )


def _ci_result_plan(
    manifest: AnalyzerManifest, repo_root: Path, ci_artifact_available: bool
) -> AnalyzerPlan | None:
    """Per-source resolver: a CI-produced artifact stands in for a local run."""
    if not ci_artifact_available:
        return None
    return AnalyzerPlan(
        manifest_id=manifest.id, mode="ci-result", cwd=repo_root, timeout_s=manifest.timeout_s
    )


def _managed_plan(
    manifest: AnalyzerManifest,
    repo_root: Path,
    *,
    managed_available: bool,
    managed_version: str | None,
) -> AnalyzerPlan | None:
    """Per-source resolver: mergeCraft's own pinned binary."""
    if not (managed_available and manifest.runtime in {"managed", "repo-native"}):
        return None
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


def _container_plan(
    manifest: AnalyzerManifest, repo_root: Path, container_available: bool
) -> AnalyzerPlan | None:
    """Per-source resolver: a sandboxed container image, last resort before skip."""
    if not (container_available and manifest.runtime == "container"):
        return None
    return AnalyzerPlan(
        manifest_id=manifest.id,
        mode="container",
        argv=tuple(manifest.command),
        cwd=repo_root,
        timeout_s=manifest.timeout_s,
    )


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
    allow_repo_binaries: bool = True,
) -> AnalyzerPlan:
    """Resolve D4's preference chain for one manifest.

    The chain normally prefers a binary the repo provides (``.venv/bin``,
    ``node_modules/.bin``, …) over mergeCraft's pinned managed one, for every
    manifest regardless of declared ``runtime``. ``allow_repo_binaries=False``
    removes that step so only the pinned binary can run — what ``shell:
    disabled`` requires, since the working tree is then PR-authored (#35, D5).

    The ladder is a small ordered dispatch of per-source resolvers —
    declared-unavailable → agentsec special-case → repo-native →
    type-checker-only-skip → managed → container — each either producing a
    plan or yielding (``None``) to the next.
    """
    if not allow_repo_binaries:
        repo_has_tool = False

    plan = _declared_unavailable_plan(manifest)
    if plan is not None:
        return plan

    plan = _agentsec_plan(manifest, repo_root)
    if plan is not None:
        return plan

    repo_tool_state, early_skip = _detect_repo_tool_state(
        manifest,
        repo_root,
        repo_has_tool=repo_has_tool,
        repo_tool_path=repo_tool_path,
        repo_tool_version=repo_tool_version,
    )
    if early_skip is not None:
        return early_skip

    resolvers: tuple[Callable[[], AnalyzerPlan | None], ...] = (
        lambda: _repo_native_plan(manifest, repo_root, repo_tool_state),
        lambda: _type_checker_missing_plan(manifest),
        lambda: _ci_result_plan(manifest, repo_root, ci_artifact_available),
        lambda: _managed_plan(
            manifest,
            repo_root,
            managed_available=managed_available,
            managed_version=managed_version,
        ),
        lambda: _container_plan(manifest, repo_root, container_available),
    )
    for resolver in resolvers:
        plan = resolver()
        if plan is not None:
            return plan

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
