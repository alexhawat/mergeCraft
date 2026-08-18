"""Safe repo-relative path helpers for analyzer scratch writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.review_policy.paths import normalize_repo_path

if TYPE_CHECKING:
    from pathlib import Path


def safe_repo_relative_path(repo_root: Path, rel: str) -> Path | None:
    """Return a resolved path under ``repo_root``, or None when ``rel`` escapes."""
    root = repo_root.resolve()
    try:
        candidate = (root / rel).resolve()
    except OSError, ValueError:
        return None
    if candidate == root or root in candidate.parents:
        return candidate
    return None


__all__ = ["normalize_repo_path", "safe_repo_relative_path"]
