"""CHANGELOG.md structural contract (W2.3-1).

``[Unreleased]`` must be the first release block, each block carries at most one
heading of each type, and no entry is listed both under ``[Unreleased]`` and under a
released version. The 0.1.0a5 cut left shipped entries, including a breaking
change, under a trailing ``[Unreleased]``; these checks stop that from recurring.
"""

from __future__ import annotations

import re

from tests.ci.workflow_support import REPO_ROOT

_CHANGELOG = REPO_ROOT / "CHANGELOG.md"
_H2 = re.compile(r"^## (.+)$")
_H3 = re.compile(r"^### (.+)$")


def _blocks(text: str) -> list[tuple[str, list[str]]]:
    """Return ``(heading, body_lines)`` for every ``## `` block, in file order."""
    blocks: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_fence = not in_fence
        match = None if in_fence else _H2.match(line)
        if match:
            blocks.append((match.group(1).strip(), []))
        elif blocks:
            blocks[-1][1].append(line)
    return blocks


def _entries(body: list[str]) -> list[str]:
    """Collapse each top-level bullet (with continuation lines) to one string."""
    entries: list[str] = []
    for line in body:
        if line.startswith("- "):
            entries.append(line.strip())
        elif entries and line.startswith("  ") and line.strip():
            entries[-1] += " " + line.strip()
    return entries


def _text() -> str:
    return _CHANGELOG.read_text(encoding="utf-8")


def test_unreleased_is_the_first_release_block() -> None:
    headings = [heading for heading, _ in _blocks(_text())]
    assert headings, "CHANGELOG.md has no `## ` release blocks"
    assert headings[0].lower().strip("[]") == "unreleased", (
        f"the first release block must be `## [Unreleased]`, found `## {headings[0]}`"
    )
    assert sum(1 for h in headings if h.lower().strip("[]") == "unreleased") == 1


def test_each_block_has_at_most_one_heading_per_type() -> None:
    offenders: list[str] = []
    for heading, body in _blocks(_text()):
        seen: set[str] = set()
        in_fence = False
        for line in body:
            if line.startswith("```"):
                in_fence = not in_fence
            match = None if in_fence else _H3.match(line)
            if not match:
                continue
            kind = match.group(1).strip()
            if kind in seen:
                offenders.append(f"{heading}: duplicate `### {kind}`")
            seen.add(kind)
    assert not offenders, offenders


def test_no_entry_is_both_unreleased_and_released() -> None:
    blocks = _blocks(_text())
    unreleased = {entry for heading, body in blocks[:1] for entry in _entries(body)}
    released = {entry for _, body in blocks[1:] for entry in _entries(body)}
    assert not unreleased & released, sorted(unreleased & released)
