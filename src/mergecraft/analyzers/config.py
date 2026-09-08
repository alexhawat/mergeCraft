"""Analyzer-specific config helpers (C2 credential verification policy)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from mergecraft.config.layered import load_layered_config_dict

if TYPE_CHECKING:
    from pathlib import Path

TrustTier = Literal["trusted", "untrusted"]


def raw_analyzers_block(repo_root: Path) -> dict[str, Any]:
    """Return the raw ``analyzers`` mapping from repo config, if any."""
    loaded = load_layered_config_dict(root=repo_root)
    analyzers = loaded.get("analyzers")
    return analyzers if isinstance(analyzers, dict) else {}


def trufflehog_verify_enabled(
    *,
    repo_root: Path,
    tier: TrustTier,
) -> bool:
    """Return whether TruffleHog live verification may run (C2 / D7).

    Verification is off by default and impossible on untrusted PRs (fork /
    pull_request_target). Trusted repos must opt in via
    ``analyzers.trufflehog.verify: true``.
    """
    if tier != "trusted":
        return False
    trufflehog = raw_analyzers_block(repo_root).get("trufflehog")
    if isinstance(trufflehog, dict):
        return bool(trufflehog.get("verify"))
    return False


__all__ = ["raw_analyzers_block", "trufflehog_verify_enabled"]
