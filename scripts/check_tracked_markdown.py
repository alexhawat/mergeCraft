#!/usr/bin/env python3
"""Guard: tracked public markdown must not cite decision IDs or gitignored plans.

Scans ``git ls-files '*.md'`` only — never walks the working tree — and fails
when a non-allowlisted file contains a decision-id token (``D14``), a
wave-dot token (``W4.4``), a ``Wave plan:`` preamble, or a
``.ignorelocal/waves/`` citation. Gitignored trees (``.ignorelocal/``,
``.claude/``, ``.cursor/``, ``CLAUDE.md``) are invisible because they are
not in the git listing.

Module: scripts.check_tracked_markdown
Depends: dataclasses, pathlib, re, subprocess, sys

Exports:
    Offense — one banned token in a tracked markdown file.
    list_tracked_markdown — ``git ls-files '*.md'`` paths under a repo root.
    scan_markdown — collect offenses in one file's text.
    main — CLI entry; scans every tracked markdown file and exits non-zero
        when any offense remains.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_ALLOWLIST_PATHS = frozenset(
    {
        "docs/dev/changelog-archive.md",
        "CHANGELOG.md",
    }
)
_ALLOWLIST_PREFIXES = (
    "docs/test-plans/",
    "docs/dev/test-plans/",
    "evals/",
    ".github/agents/",
    "tests/",
    "docker/",
)

_DECISION_ID = re.compile(r"\bD\d+\b")
_WAVE_DOT = re.compile(r"\bW\d+\.\d+\b")
_WAVE_PLAN = "Wave plan:"
_IGNORELOCAL_WAVES = ".ignorelocal/waves/"


class Offense:
    """One banned token found in a tracked markdown file.

    A plain class (not a dataclass) so ``importlib`` file-location loads
    used by the unit tests do not trip Python 3.14's dataclass module lookup.

    Args:
        relpath: Repo-relative posix path of the file.
        line_no: 1-based line number of the match.
        kind: ``decision-id``, ``wave-dot``, ``wave-plan``, or
            ``ignorelocal-waves``.
        text: The matched token or the offending line, stripped.
    """

    def __init__(self, relpath: str, line_no: int, kind: str, text: str) -> None:
        self.relpath = relpath
        self.line_no = line_no
        self.kind = kind
        self.text = text

    def __str__(self) -> str:
        return f"{self.relpath}:{self.line_no}: {self.kind}: {self.text}"


def _is_allowlisted(relpath: str) -> bool:
    """Return True when ``relpath`` is exempt from the public-docs scan.

    Args:
        relpath: Repo-relative posix path.

    Returns:
        bool: True when the path is the historical changelog allowlist or a
        deferred prefix (test-plans keep contract IDs; agent/eval/fixture
        trees are a follow-up).
    """
    if relpath in _ALLOWLIST_PATHS:
        return True
    return any(relpath.startswith(prefix) for prefix in _ALLOWLIST_PREFIXES)


def list_tracked_markdown(root: Path) -> list[Path]:
    """Return tracked ``*.md`` paths under ``root`` via ``git ls-files``.

    Args:
        root: Git repository root to list.

    Returns:
        list[Path]: Repo-relative paths, in git's order, excluding empties.

    Examples:
        >>> from pathlib import Path
        >>> callable(list_tracked_markdown)
        True
    """
    completed = subprocess.run(
        ["git", "ls-files", "--", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    )
    return [Path(line) for line in completed.stdout.splitlines() if line]


def scan_markdown(text: str, *, relpath: str) -> list[Offense]:
    """Return every banned token in ``text`` unless ``relpath`` is allowlisted.

    Args:
        text: File contents.
        relpath: Repo-relative posix path used for allowlist matching and
            offense attribution.

    Returns:
        list[Offense]: Empty when ``relpath`` is allowlisted or the text is
        clean.

    Examples:
        >>> [item.kind for item in scan_markdown("See D14.\\n", relpath="docs/x.md")]
        ['decision-id']
        >>> [item.kind for item in scan_markdown("See W4.4.\\n", relpath="docs/x.md")]
        ['wave-dot']
        >>> scan_markdown("See D14.\\n", relpath="docs/dev/changelog-archive.md")
        []
    """
    if _is_allowlisted(relpath):
        return []

    offenses: list[Offense] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        for match in _DECISION_ID.finditer(line):
            offenses.append(
                Offense(relpath=relpath, line_no=line_no, kind="decision-id", text=match.group(0))
            )
        for match in _WAVE_DOT.finditer(line):
            offenses.append(
                Offense(relpath=relpath, line_no=line_no, kind="wave-dot", text=match.group(0))
            )
        if _WAVE_PLAN in line:
            offenses.append(
                Offense(relpath=relpath, line_no=line_no, kind="wave-plan", text=_WAVE_PLAN)
            )
        if _IGNORELOCAL_WAVES in line:
            offenses.append(
                Offense(
                    relpath=relpath,
                    line_no=line_no,
                    kind="ignorelocal-waves",
                    text=_IGNORELOCAL_WAVES,
                )
            )
    return offenses


def main() -> int:
    """Scan every tracked markdown file and return 1 when any offense remains.

    Returns:
        int: ``0`` when every non-allowlisted tracked file is clean; ``1``
        when git listing fails or at least one offense is printed.
    """
    try:
        paths = list_tracked_markdown(REPO)
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"git ls-files '*.md' failed under {REPO}: {exc}", file=sys.stderr)
        return 1

    offenses: list[Offense] = []
    for rel in paths:
        relpath = rel.as_posix()
        full = REPO / rel
        try:
            text = full.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"cannot read {relpath}: {exc}", file=sys.stderr)
            return 1
        offenses.extend(scan_markdown(text, relpath=relpath))

    if not offenses:
        return 0

    print(
        "tracked markdown cites a decision ID, a wave-dot token (W#.#), a "
        "Wave plan: preamble, or .ignorelocal/waves/ (public docs must "
        "describe behaviour without gitignored ledgers):",
        file=sys.stderr,
    )
    for offense in offenses:
        print(f"  {offense}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
