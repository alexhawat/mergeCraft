"""Analyzer-specific config helpers (C2 credential verification policy)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import yaml

from mergecraft.config.settings import _resolve_config_path

if TYPE_CHECKING:
    from pathlib import Path

TrustTier = Literal["trusted", "untrusted"]


def _raw_analyzers(repo_root: Path) -> dict[str, Any]:
    path = _resolve_config_path(root=repo_root)
    if path is None:
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError, yaml.YAMLError:
        return {}
    if not isinstance(loaded, dict):
        return {}
    analyzers = loaded.get("analyzers")
    return analyzers if isinstance(analyzers, dict) else {}


def trufflehog_verify_enabled(
    *,
    repo_root: Path,
    tier: TrustTier,
    event: dict[str, Any] | None = None,
) -> bool:
    """Return whether TruffleHog live verification may run (C2 / D7).

    Verification is off by default and impossible on untrusted PRs (fork /
    pull_request_target). Trusted repos must opt in via
    ``analyzers.trufflehog.verify: true``.
    """
    _ = event
    if tier != "trusted":
        return False
    trufflehog = _raw_analyzers(repo_root).get("trufflehog")
    if isinstance(trufflehog, dict):
        return bool(trufflehog.get("verify"))
    return False


__all__ = ["trufflehog_verify_enabled"]
