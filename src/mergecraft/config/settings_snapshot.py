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
_DERIVED_GATEWAY_CACHE: ContextVar[RepoSettingsSnapshot | None] = ContextVar(
    "mergecraft_derived_gateway_settings_cache",
    default=None,
)


@dataclass(frozen=True, slots=True)
class RepoSettingsSnapshot:
    """Settings resolved once at run start plus a config-file integrity hash."""

    settings: RepoSettings
    config_hash: str
    repo_root: Path


def config_yaml_hash(*, root: Path) -> str:
    """Return a SHA-256 digest of layered config inputs pinned at snapshot time.

    Always includes committed ``.mergecraft/config.yaml``. When a local overlay
    is active (off-CI), ``.mergecraft/config.local.yaml`` is hashed too so
    mid-run edits to either file are detected (D2 / W4).
    """
    from mergecraft.config.layered import local_config_path, running_in_github_actions

    repo_root = root.resolve()
    digest = sha256()
    saw_bytes = False

    committed = repo_root / _CONFIG_REL
    if committed.is_file():
        digest.update(committed.read_bytes())
        saw_bytes = True

    if not running_in_github_actions():
        local_path = local_config_path(repo_root)
        if local_path.is_file():
            digest.update(local_path.read_bytes())
            saw_bytes = True

    if not saw_bytes:
        return ""
    return digest.hexdigest()


def reset_gateway_settings_cache() -> None:
    """Clear derived gateway settings and run-scope snapshot ContextVar state."""
    _DERIVED_GATEWAY_CACHE.set(None)
    _RUN_SCOPE_SNAPSHOT.set(None)


def run_scope_settings_snapshot() -> RepoSettingsSnapshot | None:
    """Return the run-scope settings snapshot when one is installed."""
    return _RUN_SCOPE_SNAPSHOT.get()


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


def rebaseline_repo_settings_snapshot(ctx: ToolContext) -> RepoSettingsSnapshot:
    """Re-pin the config hash after ``checkout_pr`` materializes the PR head (D14).

    ``checkout_pr`` checks out the PR branch, so ``.mergecraft/config.yaml`` on
    disk may legitimately differ from the snapshot taken at run start. Re-baseline
    once at the controlled checkout boundary; edits after that still trip
    :func:`assert_config_unchanged`.
    """
    from mergecraft.mcp.tool_state import primary_repo_state

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd()).resolve()
    prior = ctx.repo_settings_snapshot
    settings = prior.settings if prior is not None else None
    snapshot = capture_repo_settings_snapshot(
        root=repo_root,
        settings=settings,
        load_learnings_files=False,
    )
    ctx.repo_settings_snapshot = snapshot
    return snapshot


def assert_config_unchanged(snapshot: RepoSettingsSnapshot) -> None:
    """Refuse when pinned config inputs changed after the snapshot was taken."""
    baseline = snapshot.config_hash
    if not baseline:
        return
    current = config_yaml_hash(root=snapshot.repo_root)
    if current != baseline:
        msg = (
            ".mergecraft/config.yaml changed after settings were snapshotted "
            "(including any active local overlay); refusing to proceed"
        )
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

    repo_root = (root or Path.cwd()).resolve()
    derived = _DERIVED_GATEWAY_CACHE.get()
    if (
        derived is not None
        and derived.repo_root == repo_root
        and config_yaml_hash(root=repo_root) == derived.config_hash
    ):
        return derived.settings

    settings = load_repo_settings(
        root=repo_root,
        load_learnings_files=False,
    )
    _DERIVED_GATEWAY_CACHE.set(
        RepoSettingsSnapshot(
            settings=settings,
            config_hash=config_yaml_hash(root=repo_root),
            repo_root=repo_root,
        )
    )
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
    "rebaseline_repo_settings_snapshot",
    "repo_settings_for_gateway_resolvers",
    "repo_settings_from_context",
    "reset_gateway_settings_cache",
    "run_scope_settings_snapshot",
]
