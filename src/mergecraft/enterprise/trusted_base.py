"""Resolve the operator-side config a run may take trust-sensitive settings from.

Enterprise controls (telemetry, residency allow-list, retention) and remote trace
sink destinations constrain the party that triggers a review, so on a pull-request
run they are read from the PR's **base** rather than from the checkout under
review. This module decides which config that is, the same way
:mod:`mergecraft.analyzers.settings_pin` does for analyzer settings:

* ``run_start`` — a trusted run with no PR base: the run-start settings are the
  operator's own tree;
* ``base_snapshot`` — a ``pull_request_target`` run: the run-start tree *is* the
  base checkout;
* ``base_sha`` — ``git show <base>:.mergecraft/config.yaml`` for events whose
  run-start tree is the PR head;
* ``unreadable`` — a PR base exists but its config cannot be read; callers fail
  closed;
* ``none`` — an untrusted run with no PR base at all (an offline review of a
  clone): nothing in the tree is operator-owned, so built-in defaults apply.

When no explicit event is passed, the event is taken from the bound
:class:`~mergecraft.tracing.review_context.ReviewContext` (``trigger`` is the
event name the entry point recorded once) and, for an Action run, the
``GITHUB_EVENT_PATH`` payload.

Exports:
    TrustedBase: The resolved operator-side settings and where they came from.
    read_trusted_base: Resolve :class:`TrustedBase` for a run.
    context_trust_tier: The trust tier the bound review context reports.
    trusted_enterprise_block: The enterprise block an untrusted run may bind.
    reset_trusted_base_cache: Clear the per-process base-config cache (tests).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from loguru import logger

from mergecraft.enterprise.controls import EnterpriseSettings

if TYPE_CHECKING:
    from mergecraft.config.settings import RepoSettings

__all__ = [
    "TrustedBase",
    "context_trust_tier",
    "read_trusted_base",
    "reset_trusted_base_cache",
    "trusted_enterprise_block",
]

TrustedBaseSource = Literal["run_start", "base_snapshot", "base_sha", "unreadable", "none"]

_BASE_CACHE: dict[tuple[str, str], RepoSettings] = {}


@dataclass(frozen=True, slots=True)
class TrustedBase:
    """Operator-side settings for a run, plus their provenance.

    Attributes:
        settings: The operator-side settings, or ``None`` when there are none
            (``unreadable`` / ``none``).
        source: Where ``settings`` were resolved from.
        detail: A human-readable reason for a fallback, when there is one.
    """

    settings: RepoSettings | None
    source: TrustedBaseSource
    detail: str | None = None

    @property
    def from_pr_head(self) -> bool:
        """Whether the run-start tree is the PR head (its config is not operator-owned)."""
        return self.source in ("base_sha", "unreadable")


def reset_trusted_base_cache() -> None:
    """Clear the per-process base-config cache (test isolation)."""
    _BASE_CACHE.clear()


def context_trust_tier() -> str | None:
    """Return the trust tier the bound review context reports, or ``None`` when unbound.

    The resolved ``trust_tier`` wins; before it is stamped (an Action run builds
    its tracer before trust resolution), the pre-binding ``raw_event_trust_floor``
    is used. A bound context with neither reports ``"untrusted"``.
    """
    from mergecraft.tracing.review_context import current_review_context

    ctx = current_review_context()
    if ctx is None:
        return None
    return ctx.trust_tier or ctx.raw_event_trust_floor or "untrusted"


def _context_event() -> tuple[dict[str, Any] | None, str]:
    """The event payload and event name for the bound review context."""
    from mergecraft.tracing.review_context import current_review_context

    ctx = current_review_context()
    if ctx is None:
        return None, ""
    event: dict[str, Any] | None = None
    if ctx.source == "action":
        try:
            from mergecraft.utils.payload import read_github_event

            event = read_github_event()
        except Exception as exc:  # an unreadable event file declares no PR base
            logger.debug("trusted base: event payload unreadable: {}", exc)
    return event, ctx.trigger


def _event_base(event: dict[str, Any] | None) -> tuple[str, str]:
    """Return ``(base sha, base ref)`` from a pull-request event; either may be empty."""
    pull = event.get("pull_request") if isinstance(event, dict) else None
    base = pull.get("base") if isinstance(pull, dict) else None
    if not isinstance(base, dict):
        return "", ""
    sha = base.get("sha")
    ref = base.get("ref")
    return (
        sha.strip() if isinstance(sha, str) else "",
        ref.strip() if isinstance(ref, str) else "",
    )


def _read_base_config(repo_root: Path, sha: str, ref: str) -> TrustedBase:
    """Read ``.mergecraft/config.yaml`` at the PR base commit from the local checkout."""
    from mergecraft.analyzers.settings_pin import (
        _CONFIG_REL,
        _MAX_CONFIG_BYTES,
        _git,
        _resolvable_base,
        repo_settings_from_text,
    )
    from mergecraft.config.settings import default_settings

    key = (str(repo_root), sha or f"origin/{ref}")
    cached = _BASE_CACHE.get(key)
    if cached is not None:
        return TrustedBase(cached, "base_sha")
    try:
        base = _resolvable_base(repo_root, sha, ref)
        if base is None:
            return TrustedBase(None, "unreadable", "the PR base is not available in the checkout")
        listed = _git(repo_root, "ls-tree", base, "--", _CONFIG_REL)
        entry = listed.stdout.decode("utf-8", errors="replace").strip()
        if listed.returncode != 0:
            return TrustedBase(None, "unreadable", f"could not list {_CONFIG_REL} at the PR base")
        if not entry:
            settings = default_settings()
        elif entry.split(maxsplit=1)[0] == "120000":
            return TrustedBase(None, "unreadable", f"{_CONFIG_REL} at the PR base is a symlink")
        else:
            shown = _git(repo_root, "show", f"{base}:{_CONFIG_REL}")
            if shown.returncode != 0 or len(shown.stdout) > _MAX_CONFIG_BYTES:
                return TrustedBase(
                    None, "unreadable", f"{_CONFIG_REL} at the PR base is unreadable or too large"
                )
            settings = repo_settings_from_text(shown.stdout.decode("utf-8"))
    except Exception as exc:  # any doubt about the base config fails closed
        return TrustedBase(None, "unreadable", f"the PR base config could not be read ({exc})")
    if sha:
        _BASE_CACHE[key] = settings
    return TrustedBase(settings, "base_sha")


def read_trusted_base(
    run_start: RepoSettings | None,
    *,
    trust_tier: str | None,
    event: dict[str, Any] | None = None,
    event_name: str | None = None,
    repo_root: Path | None = None,
) -> TrustedBase:
    """Resolve the operator-side settings for this run.

    Args:
        run_start: The settings loaded from the run-start tree.
        trust_tier: The run's trust tier (``None`` is treated as untrusted).
        event: The bound event payload; ``None`` reads it from the review context.
        event_name: The event name; ``None`` reads it from the review context.
        repo_root: Checkout holding the PR base commit (default: the cwd).

    Returns:
        TrustedBase: The settings an operator-controlled source declares, or
        ``None`` settings with the reason when there is no such source.
    """
    if event is None and event_name is None:
        event, event_name = _context_event()
    name = event_name or ""
    if name == "pull_request_target":
        return TrustedBase(run_start, "base_snapshot")
    sha, ref = _event_base(event)
    if sha or ref:
        root = (repo_root or Path.cwd()).resolve()
        return _read_base_config(root, sha, ref)
    if trust_tier == "trusted":
        return TrustedBase(run_start, "run_start")
    return TrustedBase(None, "none", "no operator-owned config for an untrusted run")


def trusted_enterprise_block(base: TrustedBase) -> EnterpriseSettings:
    """Return the enterprise block an untrusted run binds.

    Telemetry, residency allow-list and retention come from ``base``. Proxy and
    CA are never taken from repository config on an untrusted run. A PR base
    whose config cannot be read turns remote telemetry off (fail closed); an
    untrusted run with no operator-owned config at all keeps built-in defaults.

    Args:
        base: The resolved operator-side settings.

    Returns:
        EnterpriseSettings: The block to bind.
    """
    if base.settings is not None:
        block = base.settings.enterprise
        return block.model_copy(update={"https_proxy": "", "no_proxy": "", "ca_file": None})
    if base.source == "unreadable":
        logger.warning("enterprise controls: {}; remote telemetry is off for this run", base.detail)
        return EnterpriseSettings(telemetry="off")
    return EnterpriseSettings()
