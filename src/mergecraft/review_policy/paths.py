"""Repo-relative path normalization for review scope and policy."""

from __future__ import annotations


def normalize_repo_path(path: str) -> str:
    """Strip leading ``./`` and diff ``a/`` / ``b/`` prefixes from a repo path."""
    text = path.strip().replace("\\", "/")
    for prefix in ("./", "a/", "b/"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    return text


__all__ = ["normalize_repo_path"]
