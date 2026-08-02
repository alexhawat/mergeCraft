#!/usr/bin/env python3
"""Validate Conventional Commits subject lines.

Usage:
    uv run python scripts/check_conventional_commit.py --message "feat: add x"
    uv run python scripts/check_conventional_commit.py path/to/COMMIT_EDITMSG
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PATTERN = re.compile(
    r"^(feat|fix|docs|style|refactor|perf|test|build|ci|chore|revert|release|meta)"
    r"(\([a-z0-9._-]+\))?!?: .{1,72}$"
)


def _subject(message: str) -> str:
    return message.strip().splitlines()[0] if message.strip() else ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", help="Commit message file (commit-msg hook)")
    parser.add_argument("--message", "-m", help="Commit message text")
    args = parser.parse_args(argv)

    if args.message is not None:
        text = args.message
    elif args.path:
        text = Path(args.path).read_text(encoding="utf-8")
    else:
        parser.error("provide --message or a commit-msg file path")
        return 2

    subject = _subject(text)
    if subject.startswith(("Merge ", "Revert ")):
        return 0
    if not _PATTERN.match(subject):
        print(
            f"commit subject must match Conventional Commits (≤72 chars):\n  {subject!r}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
