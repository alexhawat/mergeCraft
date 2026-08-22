#!/usr/bin/env python3
"""Normalize mergecraft review text output for committed CLI example fixtures."""

from __future__ import annotations

import re
import sys

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DIFF_SUMMARY = re.compile(
    r"(## Diff summary\s*\n\s*\n\d+ file\(s\) changed:\n(?:- .+\n)+)",
    re.MULTILINE,
)


def normalize(text: str) -> str:
    """Return the stable diff-summary block from dry-run review output."""
    text = _ANSI.sub("", text)
    match = _DIFF_SUMMARY.search(text)
    if match is None:
        msg = "dry-run output missing ## Diff summary block"
        raise ValueError(msg)
    return match.group(1).rstrip() + "\n"


def main() -> int:
    sys.stdout.write(normalize(sys.stdin.read()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
