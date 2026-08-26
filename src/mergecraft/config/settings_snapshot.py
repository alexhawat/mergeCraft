"""Immutable repo-settings snapshot pinned before untrusted execution (MCB-19, D5)."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.config.settings import RepoSettings, load_repo_settings

if TYPE_CHECKING:
    from mergecraft.mcp.context import ToolContext


_CONFIG_REL = Path(".mergecraft") / "config.yaml"


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
    return RepoSettingsSnapshot(
        settings=resolved,
        config_hash=config_yaml_hash(root=repo_root),
        repo_root=repo_root,
    )


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
        assert_config_unchanged(snapshot)
        return snapshot.settings
    from mergecraft.mcp.tool_state import primary_repo_state

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd())
    return load_repo_settings(root=repo_root, load_learnings_files=False)


__all__ = [
    "RepoSettingsSnapshot",
    "assert_config_unchanged",
    "capture_repo_settings_snapshot",
    "config_yaml_hash",
    "repo_settings_from_context",
]
