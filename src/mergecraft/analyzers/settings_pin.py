"""Pin analyzer settings to the PR's base — a PR's own config never judges itself (#942).

Run-start trust knobs were already pinned (``trust.selfReview``, ``trust.agentSandbox``
come from the run-start snapshot), but the analyzer pipeline re-read
``.mergecraft/config.yaml`` from the PR-head checkout. A PR could therefore add
``analyzers.overrides.<id>.enabled: false``, widen the ``antislop`` ``ignore`` list or
shrink ``inlineBudget`` in its own config and have that change apply to its own review.

:func:`resolve_pinned_analyzer_settings` is the one place analyzer settings are taken
from, and it never reads the head checkout on a PR run:

* ``base_snapshot`` — an operator-owned snapshot (``pull_request_target``: the run-start
  tree *is* the base checkout);
* ``base_sha`` — ``git show <base>:.mergecraft/config.yaml`` for events whose run-start
  tree is the PR head (``pull_request``, a dispatch against a PR);
* ``run_start_snapshot`` — no PR base to read (push, offline review): the run-start
  snapshot is the operator's own tree;
* ``defaults`` — fail closed with a named reason: the base config is a symlink, or the
  base commit cannot be read. Built-in defaults only ever run *more* analyzers;
* ``live_load`` — no snapshot at all (offline/tests); the only path that reads the
  checkout.

Module: mergecraft.analyzers.settings_pin
Depends: mergecraft.config.{settings,settings_snapshot}, mergecraft.utils.git_hardening

Exports:
    Classes:
        PinnedAnalyzerSettings — Settings plus where they were resolved from.
    Functions:
        resolve_pinned_analyzer_settings — The analyzer settings this run may apply.
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from mergecraft.config.settings import AnalyzersSettings
from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from mergecraft.config.settings_snapshot import RepoSettingsSnapshot
    from mergecraft.mcp.context import ToolContext

_CONFIG_REL = ".mergecraft/config.yaml"
_MAX_CONFIG_BYTES = 1024 * 1024
_GIT_TIMEOUT_S = 30


@dataclass(frozen=True, slots=True)
class PinnedAnalyzerSettings:
    """Analyzer settings together with where they were resolved from."""

    settings: AnalyzersSettings
    resolved_from: str
    detail: str | None = None


def _event_base(event: dict[str, Any] | None) -> tuple[str, str]:
    """Return ``(base sha, base ref)`` from the bound event; either may be empty."""
    pull_request = event.get("pull_request") if isinstance(event, dict) else None
    base = pull_request.get("base") if isinstance(pull_request, dict) else None
    if not isinstance(base, dict):
        return "", ""
    sha = base.get("sha")
    ref = base.get("ref")
    return (
        sha.strip() if isinstance(sha, str) else "",
        ref.strip() if isinstance(ref, str) else "",
    )


def _git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        git_argv(["-C", str(repo_root), *args]),
        capture_output=True,
        check=False,
        timeout=_GIT_TIMEOUT_S,
    )


def _resolvable_base(repo_root: Path, sha: str, ref: str) -> str | None:
    """The first of the base sha / ``origin/<base ref>`` that names a commit here."""
    candidates = [candidate for candidate in (sha, f"origin/{ref}" if ref else "") if candidate]
    for candidate in candidates:
        probe = _git(repo_root, "rev-parse", "--verify", "--quiet", f"{candidate}^{{commit}}")
        if probe.returncode == 0:
            return candidate
    return None


def _settings_from_text(text: str) -> AnalyzersSettings:
    """Validate config text through the normal loader, in a scratch tree (no overlays)."""
    from mergecraft.config.settings import load_repo_settings

    with tempfile.TemporaryDirectory(prefix="mergecraft-base-config-") as tmp:
        target = Path(tmp) / ".mergecraft"
        target.mkdir()
        (target / "config.yaml").write_text(text, encoding="utf-8")
        return load_repo_settings(root=Path(tmp), load_learnings_files=False).analyzers


def _from_base(repo_root: Path, sha: str, ref: str) -> PinnedAnalyzerSettings:
    base = _resolvable_base(repo_root, sha, ref)
    if base is None:
        return PinnedAnalyzerSettings(
            AnalyzersSettings(),
            "defaults",
            f"the PR base ({sha or ref}) is not available in the checkout, so its analyzer "
            "config could not be read; built-in defaults apply",
        )
    tree = _git(repo_root, "ls-tree", base, "--", _CONFIG_REL)
    entry = tree.stdout.decode("utf-8", errors="replace").strip()
    if tree.returncode != 0:
        return PinnedAnalyzerSettings(
            AnalyzersSettings(),
            "defaults",
            f"could not list {_CONFIG_REL} at the PR base; built-in defaults apply",
        )
    if not entry:
        return PinnedAnalyzerSettings(
            AnalyzersSettings(), "base_sha", f"the PR base has no {_CONFIG_REL}"
        )
    mode = entry.split(maxsplit=1)[0]
    if mode == "120000":
        return PinnedAnalyzerSettings(
            AnalyzersSettings(),
            "defaults",
            f"{_CONFIG_REL} at the PR base is a symlink; refused, built-in defaults apply",
        )
    shown = _git(repo_root, "show", f"{base}:{_CONFIG_REL}")
    if shown.returncode != 0 or len(shown.stdout) > _MAX_CONFIG_BYTES:
        return PinnedAnalyzerSettings(
            AnalyzersSettings(),
            "defaults",
            f"{_CONFIG_REL} at the PR base is unreadable or too large; built-in defaults apply",
        )
    try:
        settings = _settings_from_text(shown.stdout.decode("utf-8"))
    except Exception as err:  # a malformed base config must fail closed, not crash the run
        logger.warning("analyzer settings: base config rejected — {}", err)
        return PinnedAnalyzerSettings(
            AnalyzersSettings(),
            "defaults",
            f"{_CONFIG_REL} at the PR base is invalid ({err}); built-in defaults apply",
        )
    return PinnedAnalyzerSettings(settings, "base_sha")


def _snapshot(ctx: ToolContext) -> RepoSettingsSnapshot | None:
    from mergecraft.config.settings_snapshot import run_scope_settings_snapshot

    return ctx.repo_settings_snapshot or run_scope_settings_snapshot()


def resolve_pinned_analyzer_settings(
    ctx: ToolContext, repo_root: Path | None = None
) -> PinnedAnalyzerSettings:
    """Return the analyzer settings this run may apply, and where they came from.

    Never reads ``.mergecraft/config.yaml`` from the checkout when the run carries a PR
    base. The result is cached per base on the run's tool state: ``git`` runs once.
    """
    from mergecraft.mcp.tool_state import primary_repo_state

    root = (repo_root or Path(primary_repo_state(ctx.tool_state).dir or Path.cwd())).resolve()
    sha, ref = _event_base(ctx.gh_event)
    snapshot = _snapshot(ctx)
    key = (str(root), sha, ref, snapshot.operator_owned if snapshot is not None else None)
    cached = getattr(ctx.tool_state, "pinned_analyzer_settings", None)
    if (
        isinstance(cached, tuple)
        and cached[0] == key
        and isinstance(cached[1], PinnedAnalyzerSettings)
    ):
        return cached[1]

    if snapshot is not None and snapshot.operator_owned:
        pinned = PinnedAnalyzerSettings(snapshot.settings.analyzers, "base_snapshot")
    elif sha or ref:
        pinned = _from_base(root, sha, ref)
    elif snapshot is not None:
        pinned = PinnedAnalyzerSettings(snapshot.settings.analyzers, "run_start_snapshot")
    else:
        from mergecraft.config.settings import load_repo_settings

        pinned = PinnedAnalyzerSettings(
            load_repo_settings(root=root, load_learnings_files=False).analyzers, "live_load"
        )
    if pinned.resolved_from != "defaults":
        # A fail-closed fallback is recomputed: the base may simply not have been fetched
        # yet (``checkout_pr`` fetches it), and a stale "unreadable" must not outlive that.
        ctx.tool_state.pinned_analyzer_settings = (key, pinned)
    return pinned


__all__ = ["PinnedAnalyzerSettings", "resolve_pinned_analyzer_settings"]
