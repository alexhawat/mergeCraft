"""Extract failing file paths from CI log excerpts."""

from __future__ import annotations

import re

_SOURCE_EXTENSIONS = (
    "py",
    "js",
    "ts",
    "tsx",
    "jsx",
    "go",
    "rs",
    "java",
    "rb",
    "php",
    "md",
    "yaml",
    "yml",
    "json",
    "toml",
    "cs",
    "kt",
    "swift",
)
_EXT_GROUP = "|".join(_SOURCE_EXTENSIONS)
# The directory prefix is optional so root-level files are extracted, but only
# inside the failure-context patterns below — never from a bare path-shaped token.
_REPO_PATH = rf"(?:[\w.-]+/)*[\w.-]+\.(?:{_EXT_GROUP})"

_FAILED_TEST = re.compile(rf"\b(?:FAILED|ERROR)\s+({_REPO_PATH}(?:::[\w_]+)?)", re.I)
_TRACE_FILE = re.compile(rf"^\s*({_REPO_PATH}):(\d+):", re.M | re.I)
_COMPILER_ERROR = re.compile(rf"^\s*({_REPO_PATH})\((\d+),\s*\d+\)", re.M | re.I)


def normalize_repo_path(path: str) -> str:
    """Return ``path`` as a repo-relative path: strip leading ``./`` and collapse ``//``."""
    normalized = path.strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    while "//" in normalized:
        normalized = normalized.replace("//", "/")
    return normalized


def extract_failure_paths(log_excerpt: str) -> list[str]:
    """Return repo-relative paths implicated in a failure excerpt, in encounter order.

    Paths are read only from failure-context forms — a ``FAILED`` / ``ERROR`` node
    report, a line-start ``path:line:`` citation, or a ``path(line,col)`` compiler
    citation — and each is normalised. A path-shaped token anywhere else (a
    ``PASSED`` line, a collection line, a command echo, a bare URL) is not a
    failure location.
    """
    seen: set[str] = set()
    paths: list[str] = []

    def _add(raw: str) -> None:
        candidate = raw.split("::", 1)[0]
        if candidate.startswith(("/", "\\")) or "://" in candidate:
            return
        path = normalize_repo_path(candidate)
        if not path:
            return
        if path not in seen:
            seen.add(path)
            paths.append(path)

    for match in _FAILED_TEST.finditer(log_excerpt):
        _add(match.group(1))
    for match in _TRACE_FILE.finditer(log_excerpt):
        _add(match.group(1))
    for match in _COMPILER_ERROR.finditer(log_excerpt):
        _add(match.group(1))
    return paths


def primary_failure_path(log_excerpt: str) -> str:
    """Best-effort primary path for clustering and cross-source merge keys."""
    paths = extract_failure_paths(log_excerpt)
    if paths:
        return paths[0]
    return "ci/pipeline"


def failure_line(log_excerpt: str, *, path: str) -> int:
    """Return a 1-based line number when the traceback cites ``path``.

    Accepts the ``path:line:`` citation with an optional ``./`` prefix and the
    ``path(line,col)`` compiler citation, both against a normalised ``path``.
    """
    target = normalize_repo_path(path)
    if not target:
        return 1
    escaped = re.escape(target)
    patterns = (
        rf"^\s*\.?/?{escaped}:(\d+):",
        rf"^\s*\.?/?{escaped}\((\d+),\s*\d+\)",
    )
    for pattern in patterns:
        match = re.search(pattern, log_excerpt, re.M)
        if match:
            return max(int(match.group(1)), 1)
    return 1


__all__ = [
    "extract_failure_paths",
    "failure_line",
    "normalize_repo_path",
    "primary_failure_path",
]
