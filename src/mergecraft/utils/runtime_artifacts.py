"""Identify generated, untracked paths excluded from local review source.

Callers must first establish that a path is untracked. A tracked file at the
same location remains source and must participate in diffs and cache identity.
"""

from __future__ import annotations

_DIRECTORIES = (".mergecraft/reviews", ".mergecraft/analyzer-cache")


def is_untracked_runtime_artifact(path: str) -> bool:
    """Recognize default review storage, managed analyzers and legacy audit log."""
    return path == ".mergecraft/audit.jsonl" or any(
        path == directory or path.startswith(f"{directory}/") for directory in _DIRECTORIES
    )
