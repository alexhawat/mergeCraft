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


def assert_config_unchanged(snapshot: RepoSettingsSnapshot) -> None:
    """Refuse when ``.mergecraft/config.yaml`` changed after the snapshot was taken."""
    current = config_yaml_hash(root=snapshot.repo_root)
    if current != snapshot.config_hash:
        msg = ".mergecraft/config.yaml changed after settings were snapshotted; refusing to proceed"
        raise ValueError(msg)


def repo_settings_from_context(ctx: ToolContext) -> RepoSettings:
    """Read the run-scope settings snapshot, falling back to a live load when unset."""
    snapshot = ctx.repo_settings_snapshot
    if snapshot is not None:
        return snapshot.settings
    from mergecraft.mcp.tool_state import primary_repo_state

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd())
    return load_repo_settings(root=repo_root, load_learnings_files=False)


def repo_settings_for_gateway_resolvers(*, root: Path | None = None) -> RepoSettings:
    """Return repo settings for gateway credential resolution (AG9 / #496).

    Prefer the AG2 run-scope snapshot when installed. Otherwise live-load once
    per context and reuse the derived value for the gateway hot path.
    """
    snapshot = _RUN_SCOPE_SNAPSHOT.get()
    if snapshot is not None:
        return snapshot.settings

    derived = _DERIVED_GATEWAY_SETTINGS.get()
    if derived is not None:
        return derived

    repo_root = (root or Path.cwd()).resolve()
    import mergecraft.config.settings_snapshot as snapshot_module

    settings = snapshot_module.load_repo_settings(
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
    "config_yaml_hash",
    "load_repo_settings",
    "repo_settings_for_gateway_resolvers",
    "repo_settings_from_context",
    "reset_gateway_settings_cache",
]
