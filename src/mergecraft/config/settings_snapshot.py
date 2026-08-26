"""Immutable repo-settings snapshot pinned before untrusted execution (MCB-19, D5)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings
    from mergecraft.mcp.context import ToolContext


_CONFIG_REL = Path(".mergecraft") / "config.yaml"

_RUN_SCOPE_SNAPSHOT: ContextVar[RepoSettingsSnapshot | None] = ContextVar(
    "mergecraft_run_scope_settings_snapshot",
    default=None,
)
_DERIVED_GATEWAY_SETTINGS: ContextVar[RepoSettings | None] = ContextVar(
    "mergecraft_derived_gateway_settings",
    default=None,
)


@dataclass(frozen=True, slots=True)
class RepoSettingsSnapshot:
    """Settings resolved once at run start plus a config-file integrity hash."""

    settings: RepoSettings
    config_hash: str
    repo_root: Path


def config_yaml_hash(*, root: Path) -> str:
    """Return a SHA-256 digest of ``.mergecraft/config.yaml``, or ``""`` when absent."""
    config_path = root / _CONFIG_REL
    if not config_path.is_file():
        return ""
    return sha256(config_path.read_bytes()).hexdigest()


def reset_gateway_settings_cache() -> None:
    """Clear derived gateway settings and run-scope snapshot ContextVar state."""
    _DERIVED_GATEWAY_SETTINGS.set(None)
    _RUN_SCOPE_SNAPSHOT.set(None)


def capture_repo_settings_snapshot(
    *,
    root: Path,
    settings: RepoSettings | None = None,
    load_learnings_files: bool = False,
) -> RepoSettingsSnapshot:
    """Resolve settings once and record the config hash for later fail-closed checks."""
    repo_root = root.resolve()
    resolved = settings or load_repo_settings(
        root=repo_root,
        load_learnings_files=load_learnings_files,
    )
    snapshot = RepoSettingsSnapshot(
        settings=resolved,
        config_hash=config_yaml_hash(root=repo_root),
        repo_root=repo_root,
    )
    _RUN_SCOPE_SNAPSHOT.set(snapshot)
    return snapshot


def capture_run_scope_snapshot(
    ctx: ToolContext,
    *,
    root: Path,
    settings: RepoSettings | None = None,
    load_learnings_files: bool = False,
) -> RepoSettingsSnapshot:
    """Pin repo settings on ``ctx`` and the run-scope ContextVar in one write."""
    snapshot = capture_repo_settings_snapshot(
        root=root,
        settings=settings,
        load_learnings_files=load_learnings_files,
    )
    ctx.repo_settings_snapshot = snapshot
    return snapshot


def assert_config_unchanged(snapshot: RepoSettingsSnapshot) -> None:
    """Refuse when ``.mergecraft/config.yaml`` changed after the snapshot was taken."""
    current = config_yaml_hash(root=snapshot.repo_root)
    if current != snapshot.config_hash:
        msg = ".mergecraft/config.yaml changed after settings were snapshotted; refusing to proceed"
        raise ValueError(msg)


def _snapshot_from_context(ctx: ToolContext) -> RepoSettingsSnapshot | None:
    return ctx.repo_settings_snapshot or _RUN_SCOPE_SNAPSHOT.get()


def repo_settings_from_context(ctx: ToolContext) -> RepoSettings:
    """Read the run-scope settings snapshot, with a live-load fallback.

    Production runs must install a snapshot via :func:`capture_run_scope_snapshot`
    before untrusted execution. The live-load fallback exists for offline runs,
    unit tests, and other contexts that never pin a snapshot — it must not be
    relied on for publish or gate decisions in production.
    """
    snapshot = _snapshot_from_context(ctx)
    if snapshot is not None:
        assert_config_unchanged(snapshot)
        return snapshot.settings
    from mergecraft.mcp.tool_state import primary_repo_state

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd())
    return load_repo_settings(root=repo_root, load_learnings_files=False)


def pinned_repo_settings_from_context(ctx: ToolContext) -> RepoSettings | None:
    """Return snapshotted settings without re-checking disk (fail-closed paths only)."""
    snapshot = _snapshot_from_context(ctx)
    if snapshot is None:
        return None
    return snapshot.settings


def repo_settings_for_gateway_resolvers(*, root: Path | None = None) -> RepoSettings:
    """Return repo settings for gateway credential resolution (AG9 / #496).

    Prefer the AG2 run-scope snapshot when installed and refuse when
    ``.mergecraft/config.yaml`` changed after the snapshot (same fail-closed
    posture as publish/gate paths). When no snapshot is installed — offline
    CLIs, unit tests, and other contexts that never call
    :func:`capture_run_scope_snapshot` — live-load once per context and reuse
    the derived value for the gateway hot path. That fallback must not be
    relied on for production review runs.
    """
    snapshot = _RUN_SCOPE_SNAPSHOT.get()
    if snapshot is not None:
        assert_config_unchanged(snapshot)
        return snapshot.settings

    derived = _DERIVED_GATEWAY_SETTINGS.get()
    if derived is not None:
        return derived

    repo_root = (root or Path.cwd()).resolve()
    settings = load_repo_settings(
        root=repo_root,
        load_learnings_files=False,
    )
    _DERIVED_GATEWAY_SETTINGS.set(settings)
    return settings


def load_repo_settings(
    path: Path | str | None = None,
    *,
    root: Path | None = None,
    load_learnings_files: bool = False,
) -> RepoSettings:
    """Live-load repo settings for gateway helpers (AG9 / #496)."""
    from mergecraft.config.settings import load_repo_settings as _load_repo_settings

    return _load_repo_settings(
        path,
        root=root,
        load_learnings_files=load_learnings_files,
    )


__all__ = [
    "RepoSettingsSnapshot",
    "assert_config_unchanged",
    "capture_repo_settings_snapshot",
    "capture_run_scope_snapshot",
    "config_yaml_hash",
    "load_repo_settings",
    "pinned_repo_settings_from_context",
    "repo_settings_for_gateway_resolvers",
    "repo_settings_from_context",
    "reset_gateway_settings_cache",
]
