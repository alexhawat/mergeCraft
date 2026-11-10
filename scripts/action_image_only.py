"""Recognize a sole edit to the canonical runs.image scalar in the root Action."""

from __future__ import annotations

import re
import subprocess
import sys

_IMAGE = re.compile(rb'^  image: "(?P<value>[A-Za-z0-9./:@_+-]+)"$', re.MULTILINE)
_RUNS = re.compile(rb"^runs:\n((?:[ \t][^\n]*\n|\n)+)", re.MULTILINE)


def image_span(manifest: bytes) -> tuple[int, int] | None:
    """Locate the unambiguous scalar in the trusted manifest's canonical layout."""
    sections = list(_RUNS.finditer(manifest))
    if len(sections) != 1:
        return None
    section = sections[0]
    matches = list(_IMAGE.finditer(manifest, *section.span(1)))
    return matches[0].span("value") if len(matches) == 1 else None


def image_only(base: str, head: str) -> bool:
    """Prove a regular-file modification, identical bytes outside the scalar."""
    if not all(re.fullmatch("[0-9a-f]{40}", sha) for sha in (base, head)):
        return False

    def git(*args: str) -> bytes:
        return subprocess.check_output(["git", *args], timeout=30)

    # Comparing just the tips of diverged branches can hide changes in the PR diff.
    if git("merge-base", base, head).strip().decode() != base:
        return False
    change = git("diff", "--raw", "-z", "--no-renames", "--ignore-submodules=none", base, head)
    if not re.fullmatch(rb":100644 100644 [0-9a-f]+ [0-9a-f]+ M\x00action\.yml\x00", change):
        return False
    before, after = (git("show", f"{sha}:action.yml") for sha in (base, head))
    span = image_span(before)
    if span is None:
        return False
    start, end = span
    # Match the entire candidate against trusted bytes with exactly one scalar slot.
    return (
        bool(
            re.fullmatch(
                re.escape(before[:start]) + rb"[A-Za-z0-9./:@_+-]+" + re.escape(before[end:]),
                after,
            )
        )
        and before != after
    )


if __name__ == "__main__":
    try:
        matched = image_only(*sys.argv[1:])
    except (OSError, subprocess.SubprocessError):
        matched = False
    print(f"image_only={str(matched).lower()}")
