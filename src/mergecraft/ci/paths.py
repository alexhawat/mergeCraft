"""Extract failing file paths from CI log excerpts."""

from __future__ import annotations

import re

_FAILED_TEST = re.compile(
    r"FAILED\s+((?:tests|src|scripts)/[^\s:]+\.py(?:::[\w_]+)?)",
    re.I,
)
_ERROR_FILE = re.compile(
    r"^\s*((?:tests|src|scripts)/[^\s:]+\.py):\d+:",
    re.M,
)
_SPEC_PATH = re.compile(r"(about-sevn\.bot/specs/[^\s]+\.md)", re.I)
_SCRIPT_PATH = re.compile(r"(scripts/[^\s]+\.py)", re.I)


def extract_failure_paths(log_excerpt: str) -> list[str]:
    """Return repo-relative paths implicated in a failure excerpt, in encounter order."""
    seen: set[str] = set()
    paths: list[str] = []

    def _add(raw: str) -> None:
        path = raw.split("::", 1)[0]
        if path not in seen:
            seen.add(path)
            paths.append(path)

    for match in _FAILED_TEST.finditer(log_excerpt):
        _add(match.group(1))
    for match in _ERROR_FILE.finditer(log_excerpt):
        _add(match.group(1))
    for match in _SPEC_PATH.finditer(log_excerpt):
        _add(match.group(1))
    for match in _SCRIPT_PATH.finditer(log_excerpt):
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
