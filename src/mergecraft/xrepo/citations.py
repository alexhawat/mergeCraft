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


_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")


def validate_citation(citation: Citation) -> None:
    """Validate that a citation carries repo, SHA, path, and line range."""
    if not citation.repo.strip():
        msg = "citation.repo is required"
        raise CitationError(msg)
    if not _SHA_RE.fullmatch(citation.sha.lower()):
        msg = f"citation.sha must be a git object id; got {citation.sha!r}"
        raise CitationError(msg)
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


__all__ = ["Citation", "CitationError", "format_citation", "validate_citation"]
