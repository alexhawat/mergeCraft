"""Similar issues and similar changes — advisory matches (output-only).

Library helpers for #351. Callers pass in catalogs or a repo root; nothing is
written to the reviewed tree (D13).
"""

from __future__ import annotations

import re
import subprocess
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_TOKEN_RE = re.compile(r"[a-z0-9]+")


class SimilarIssue(BaseModel):
    """One advisory issue match — never filed or mutated."""

    model_config = ConfigDict(extra="forbid")

    title: str
    number: int | None = None
    score: float = 0.0


class SimilarChange(BaseModel):
    """One advisory prior-change match — never checked out or rewritten."""

    model_config = ConfigDict(extra="forbid")

    title: str
    sha: str | None = None
    paths: list[str] = Field(default_factory=list)
    score: float = 0.0


def _tokens(text: str) -> frozenset[str]:
    return frozenset(_TOKEN_RE.findall(text.casefold()))


def _overlap_score(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def find_similar_issues(
    *,
    title: str,
    candidates: Sequence[Mapping[str, object]] | None = None,
    limit: int = 5,
) -> list[SimilarIssue]:
    """Rank candidate issues by title-token overlap. Never writes."""
    query = _tokens(title)
    matches: list[SimilarIssue] = []
    for raw in candidates or ():
        candidate_title = raw.get("title")
        if not isinstance(candidate_title, str) or not candidate_title.strip():
            continue
        score = _overlap_score(query, _tokens(candidate_title))
        if score <= 0.0:
            continue
        number = raw.get("number")
        matches.append(
            SimilarIssue(
                title=candidate_title.strip(),
                number=number if isinstance(number, int) else None,
                score=score,
            )
        )
    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[: max(limit, 0)]


def _git_change_candidates(repo_root: Path) -> list[dict[str, object]]:
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return []
    try:
        completed = subprocess.run(
            ["git", "log", "-n", "30", "--pretty=format:%H\t%s", "--name-only"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if completed.returncode != 0:
        return []

    candidates: list[dict[str, object]] = []
    sha: str | None = None
    title = ""
    paths: list[str] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            if sha is not None:
                candidates.append({"sha": sha, "title": title, "paths": paths})
            sha = None
            title = ""
            paths = []
            continue
        if "\t" in line and sha is None:
            sha, _, title = line.partition("\t")
            paths = []
            continue
        if sha is not None:
            paths.append(line)
    if sha is not None:
        candidates.append({"sha": sha, "title": title, "paths": paths})
    return candidates


def find_similar_changes(
    *,
    paths: Sequence[str],
    candidates: Sequence[Mapping[str, object]] | None = None,
    repo_root: Path | None = None,
    limit: int = 5,
) -> list[SimilarChange]:
    """Rank prior changes by overlapping paths. Never writes."""
    wanted = {path for path in paths if path}
    catalog: Sequence[Mapping[str, object]]
    if candidates is not None:
        catalog = candidates
    elif repo_root is not None:
        catalog = _git_change_candidates(repo_root)
    else:
        catalog = []

    matches: list[SimilarChange] = []
    for raw in catalog:
        raw_paths = raw.get("paths")
        change_paths = (
            [str(path) for path in raw_paths if isinstance(path, str) and path]
            if isinstance(raw_paths, list)
            else []
        )
        overlap = wanted & set(change_paths) if wanted else set()
        if wanted and not overlap:
            continue
        title = raw.get("title")
        sha = raw.get("sha")
        score = (len(overlap) / len(wanted)) if wanted else 0.0
        matches.append(
            SimilarChange(
                title=title.strip() if isinstance(title, str) else "",
                sha=sha if isinstance(sha, str) else None,
                paths=sorted(overlap or change_paths),
                score=score,
            )
        )
    matches.sort(key=lambda item: item.score, reverse=True)
    return matches[: max(limit, 0)]


__all__ = [
    "SimilarChange",
    "SimilarIssue",
    "find_similar_changes",
    "find_similar_issues",
]
