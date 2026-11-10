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
    from mergecraft.policy.review import PolicySnapshot


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
    """Settings resolved once at run start plus a config-file integrity hash.

    ``operator_owned`` is the sole authority tracing's D7 cap consults to
    decide whether this snapshot's ``tracing.exportUntrustedContent`` may
    lift the untrusted-run body-export cap (see
    :func:`mergecraft.tracing.genai._yaml_export_untrusted_for_capture`).
    It is ``True`` only when ``settings`` is known — by the caller that
    captured it, not inferred here — to have been read from a checkout a
    fork cannot control: the base ref on a ``pull_request_target`` run,
    before :func:`rebaseline_repo_settings_snapshot` re-points at the PR
    head. Every other capture (trusted runs don't need it; other untrusted
    event shapes check out the fork head from the start; a rebaseline with
    no prior snapshot falls back to a live load off whatever is on disk,
    which may already be the fork's own HEAD) defaults to ``False`` —
    fail closed, matching D6/D7's "safe default" posture. This is a
    property of *how the value was obtained*, never of the YAML content
    itself — fork-controlled HEAD YAML is never operator-owned regardless
    of what it says.
    """

    settings: RepoSettings
    config_hash: str
    repo_root: Path
    operator_owned: bool = False
    # Policy-as-code documents pinned with the settings, so a run applies one
    # copy of the rules: the operator-owned one this capture read, or — when a
    # pull request controls the working tree — whatever ``policy/review.py``
    # resolves from the base commit. ``None`` means policy was never captured.
    policy: PolicySnapshot | None = None


_NO_CONFIG_MARKER = b"mergecraft:no-config-files"


def config_yaml_hash(*, root: Path) -> str:
    """Return a SHA-256 digest of the config inputs the layered loader reads.

    The inputs come from :func:`mergecraft.config.layered.resolve_config_sources`,
    the same resolver the loader's precedence mirrors: an existing
    ``MERGECRAFT_CONFIG`` file is the sole contributor; otherwise the committed
    ``.mergecraft/config.yaml`` plus, off CI, ``.mergecraft/config.local.yaml``.
    Each contributing file is hashed with its resolved path, so switching the
    selected file or editing it mid-run is detected, while edits to a file the
    loader ignores are not.

    When no file contributes, a stable sentinel digest is returned (never the
    empty string) so a config file appearing later is a detectable change.
    Raises :class:`ValueError` when a contributing file cannot be read — callers
    must treat that as fail-closed.
    """
    from mergecraft.config.layered import resolve_config_sources

    sources = resolve_config_sources(root.resolve())
    digest = sha256()
    if not sources.files:
        digest.update(_NO_CONFIG_MARKER)
        if sources.env_config_missing:
            digest.update(b":env-config-missing")
        return digest.hexdigest()
    for path in sources.files:
        try:
            body = path.read_bytes()
        except OSError as exc:
            msg = f"cannot hash config file {path} ({type(exc).__name__}); refusing to proceed"
            raise ValueError(msg) from exc
        digest.update(str(path).encode("utf-8", "surrogateescape"))
        digest.update(b"\0")
        digest.update(body)
        digest.update(b"\0")
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
    operator_owned: bool = False,
    policy: PolicySnapshot | None = None,
) -> RepoSettingsSnapshot:
    """Resolve settings once and record the config hash for later fail-closed checks.

    ``operator_owned`` must be passed truthfully by the caller — see
    :class:`RepoSettingsSnapshot`. It defaults to ``False`` so a caller that
    doesn't reason about it gets the fail-closed answer.

    The policy documents are captured in the same read as the settings, from the
    same root and with the same ``operator_owned`` provenance. A caller that
    already holds a snapshot's policy (a rebaseline after ``checkout_pr``) passes
    it back, so the rules that judge a pull request are never re-read from a tree
    the pull request just rewrote.
    """
    repo_root = root.resolve()
    resolved = settings or load_repo_settings(
        root=repo_root,
        load_learnings_files=load_learnings_files,
    )
    if policy is None:
        from mergecraft.policy.review import load_repo_policy

        policy = load_repo_policy(repo_root, operator_owned=operator_owned)
    snapshot = RepoSettingsSnapshot(
        settings=resolved,
        config_hash=config_yaml_hash(root=repo_root),
        repo_root=repo_root,
        operator_owned=operator_owned,
        policy=policy,
    )
    _RUN_SCOPE_SNAPSHOT.set(snapshot)
    return snapshot


def capture_run_scope_snapshot(
    ctx: ToolContext,
    *,
    root: Path,
    settings: RepoSettings | None = None,
    load_learnings_files: bool = False,
    operator_owned: bool = False,
) -> RepoSettingsSnapshot:
    """Pin repo settings on ``ctx`` and the run-scope ContextVar in one write."""
    snapshot = capture_repo_settings_snapshot(
        root=root,
        settings=settings,
        load_learnings_files=load_learnings_files,
        operator_owned=operator_owned,
    )
    ctx.repo_settings_snapshot = snapshot
    return snapshot


def rebaseline_repo_settings_snapshot(ctx: ToolContext) -> RepoSettingsSnapshot:
    """Re-pin the config hash after ``checkout_pr`` materializes the PR head (D14).

    ``checkout_pr`` checks out the PR branch, so ``.mergecraft/config.yaml`` on
    disk may legitimately differ from the snapshot taken at run start. Re-baseline
    once at the controlled checkout boundary; edits after that still trip
    :func:`assert_config_unchanged`.

    When a prior snapshot exists (the production path — the run-start
    snapshot captured before ``checkout_pr`` ever runs), its ``settings``
    (and ``operator_owned`` provenance, D7) are carried forward unchanged;
    only ``config_hash``/``repo_root`` are re-derived from the now-checked-out
    head. Its ``policy`` documents are carried forward for the same reason:
    ``checkout_pr`` may have materialized a pull request that weakens or
    deletes the rules, and the rules that judge it must not change under the
    review. When there is no prior snapshot (a caller — e.g. local ``mcp
    serve`` — that never called :func:`capture_run_scope_snapshot` before
    invoking ``checkout_pr``), this falls back to a live load off whatever is
    on disk *after* checkout, which may be a fork's own HEAD. That result is
    never operator-owned regardless of what it says, so ``operator_owned`` is
    forced to ``False`` on this branch — fail closed, never inferred from
    content that could itself be fork-controlled.
    """
    from mergecraft.mcp.tool_state import primary_repo_state

    repo_root = Path(primary_repo_state(ctx.tool_state).dir or Path.cwd()).resolve()
    prior = ctx.repo_settings_snapshot
    settings = prior.settings if prior is not None else None
    operator_owned = prior.operator_owned if prior is not None else False
    snapshot = capture_repo_settings_snapshot(
        root=repo_root,
        settings=settings,
        load_learnings_files=False,
        operator_owned=operator_owned,
        policy=prior.policy if prior is not None else None,
    )
    ctx.repo_settings_snapshot = snapshot
    return snapshot


def assert_config_unchanged(snapshot: RepoSettingsSnapshot) -> None:
    """Refuse when pinned config inputs changed after the snapshot was taken."""
    baseline = snapshot.config_hash
    if not baseline:
        # Hand-built snapshots (tests, offline callers) carry no baseline.
        return
    current = config_yaml_hash(root=snapshot.repo_root)
    if current != baseline:
        msg = (
            ".mergecraft/config.yaml changed after settings were snapshotted "
            "(including any active local overlay or MERGECRAFT_CONFIG file); "
            "refusing to proceed"
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
