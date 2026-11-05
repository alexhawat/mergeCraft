"""Shared path glob matching for pipeline predicates, analyzers and declared scopes.

The matcher lives in :mod:`mergecraft.classify.path_globs`, a leaf module the
classifier can import without loading :mod:`mergecraft.utils`; it is re-exported
here for the pipeline predicates and analyzers.
"""

from __future__ import annotations

from mergecraft.classify.path_globs import path_full_matches_glob, path_matches_glob

__all__ = ["path_full_matches_glob", "path_matches_glob"]
