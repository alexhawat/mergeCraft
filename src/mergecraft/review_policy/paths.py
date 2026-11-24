"""Repo-relative path normalization for review scope and policy."""

from __future__ import annotations


def normalize_repo_path(path: str) -> str:
    """Normalize repository-relative paths after diff parsing has removed its prefixes."""
    return path.strip().replace("\\", "/").removeprefix("./")


__all__ = ["normalize_repo_path"]
