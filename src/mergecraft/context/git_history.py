"""Targeted git blame for review context with reproducible provenance."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal

from mergecraft.context.provenance import ContextItem


@dataclass(frozen=True, slots=True)
class BlameEntry:
    """One line of targeted blame attribution."""

    line: int
    commit_sha: str
    author: str
    text: str


@dataclass(frozen=True, slots=True)
class TargetedBlameResult:
    """Blame entries plus provenance for the queried range."""

    entries: tuple[BlameEntry, ...]
    provenance: ContextItem


def targeted_blame(
    *,
    repo_root: Path,
    repo: str,
    path: str,
    start_line: int,
    end_line: int,
) -> TargetedBlameResult:
    """Return line-level blame for ``path`` between ``start_line`` and ``end_line``."""
    head_sha = _git_rev_parse(repo_root, "HEAD")
    entries = _run_blame(
        repo_root=repo_root,
        path=path,
        start_line=start_line,
        end_line=end_line,
    )
    citation_text = "\n".join(
        f"L{entry.line} {entry.commit_sha[:8]} {entry.author}: {entry.text.rstrip()}"
        for entry in entries
    )
    provenance = ContextItem(
        repo=repo,
        sha=head_sha,
        path=path,
        reason="git_history",
        text=citation_text,
        token_cost=max(1, len(citation_text) // 4),
    )
    return TargetedBlameResult(entries=entries, provenance=provenance)


def _git_rev_parse(repo_root: Path, ref: str) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def _run_blame(
    *,
    repo_root: Path,
    path: str,
    start_line: int,
    end_line: int,
) -> tuple[BlameEntry, ...]:
    completed = subprocess.run(
        [
            "git",
            "blame",
            "-L",
            f"{start_line},{end_line}",
            "--line-porcelain",
            path,
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=True,
    )
    entries: list[BlameEntry] = []
    current_sha = ""
    current_author = ""
    current_line = start_line

    for raw in completed.stdout.splitlines():
        if raw.startswith("\t"):
            text = raw[1:]
            entries.append(
                BlameEntry(
                    line=current_line,
                    commit_sha=current_sha,
                    author=current_author,
                    text=text,
                )
            )
            current_line += 1
            continue
        parts = raw.split(maxsplit=1)
        if len(parts[0]) == 40 and all(ch in "0123456789abcdef" for ch in parts[0].casefold()):
            current_sha = parts[0]
            continue
        if raw.startswith("author "):
            current_author = raw.removeprefix("author ")
    return tuple(entries)


__all__ = ["BlameEntry", "TargetedBlameResult", "targeted_blame"]
