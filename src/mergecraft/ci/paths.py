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
_REPO_PATH = rf"(?:[\w.-]+/)+[\w.-]+\.(?:{_EXT_GROUP})"

_FAILED_TEST = re.compile(rf"FAILED\s+({_REPO_PATH}(?:::[\w_]+)?)", re.I)
_PYTEST_NODE = re.compile(rf"\b({_REPO_PATH}(?:::[\w_]+)?)\s", re.I)
_TRACE_FILE = re.compile(rf"^\s*({_REPO_PATH}):(\d+):", re.M | re.I)


def extract_failure_paths(log_excerpt: str) -> list[str]:
    """Return repo-relative paths implicated in a failure excerpt, in encounter order."""
    seen: set[str] = set()
    paths: list[str] = []

    def _add(raw: str) -> None:
        path = raw.split("::", 1)[0]
        if path.startswith(("/", "\\")) or "://" in path:
            return
        if path not in seen:
            seen.add(path)
            paths.append(path)

    for match in _FAILED_TEST.finditer(log_excerpt):
        _add(match.group(1))
    for match in _TRACE_FILE.finditer(log_excerpt):
        _add(match.group(1))
    for match in _PYTEST_NODE.finditer(log_excerpt):
        _add(match.group(1))
    return paths


def primary_failure_path(log_excerpt: str) -> str:
    """Best-effort primary path for clustering and cross-source merge keys."""
    paths = extract_failure_paths(log_excerpt)
    if paths:
        return paths[0]
    return "ci/pipeline"


def failure_line(log_excerpt: str, *, path: str) -> int:
    """Return a 1-based line number when the traceback cites ``path``."""
    pattern = re.compile(rf"^\s*{re.escape(path)}:(\d+):", re.M)
    match = pattern.search(log_excerpt)
    if match:
        return max(int(match.group(1)), 1)
    return 1


__all__ = ["extract_failure_paths", "failure_line", "primary_failure_path"]
