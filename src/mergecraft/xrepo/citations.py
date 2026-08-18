"""Reproducible cross-repo citations — repo + SHA + location (convention 4)."""

from __future__ import annotations

import re
from dataclasses import dataclass


class CitationError(ValueError):
    """Raised when a citation is missing required reproducibility fields."""


@dataclass(frozen=True, slots=True)
class Citation:
    """One reproducible cross-repo citation."""

    repo: str
    sha: str
    path: str
    start_line: int
    end_line: int


PINNED_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def validate_pinned_sha(sha: str) -> None:
    """Validate that ``sha`` is a pinned git object id (not a branch name)."""
    if not PINNED_SHA_RE.fullmatch(sha.lower()):
        msg = f"commit must be a pinned git object id; got {sha!r}"
        raise ValueError(msg)


def validate_citation(citation: Citation) -> None:
    """Validate that a citation carries repo, SHA, path, and line range."""
    if not citation.repo.strip():
        msg = "citation.repo is required"
        raise CitationError(msg)
    try:
        validate_pinned_sha(citation.sha)
    except ValueError as exc:
        raise CitationError(str(exc)) from exc
    if not citation.path.strip():
        msg = "citation.path is required"
        raise CitationError(msg)
    if citation.start_line < 1:
        msg = "citation.start_line must be >= 1"
        raise CitationError(msg)
    if citation.end_line < citation.start_line:
        msg = "citation.end_line must be >= start_line"
        raise CitationError(msg)


def format_citation(citation: Citation) -> str:
    """Format a citation as ``repo@sha:path#Lstart-Lend``."""
    validate_citation(citation)
    return (
        f"{citation.repo}@{citation.sha}:{citation.path}"
        f"#L{citation.start_line}-L{citation.end_line}"
    )


__all__ = [
    "PINNED_SHA_RE",
    "Citation",
    "CitationError",
    "format_citation",
    "validate_citation",
    "validate_pinned_sha",
]
