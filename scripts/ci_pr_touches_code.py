#!/usr/bin/env python3
"""Classify a PR diff as docs-only vs code-touching for CI path filters."""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys
from pathlib import PurePosixPath

# Paths that may change without running the full unit/coverage/integration matrix.
_DOCS_ONLY_PATTERNS: tuple[str, ...] = (
    "plans/**",
    "evals/results/**",
    "llms-full.txt",
    "llms.txt",
    "LICENSE",
    "LICENSE.*",
)

# Paths that look like docs but are guarded by tests/skills/eval sync suites.
_NEVER_DOCS_ONLY_PREFIXES: tuple[str, ...] = (
    ".github/skills/",
    "src/mergecraft/skills/",
    "evals/cases/",
)


def _matches_docs_only(path: str) -> bool:
    normalized = path.replace("\\", "/").lstrip("./")
    if not normalized:
        return False
    for prefix in _NEVER_DOCS_ONLY_PREFIXES:
        if normalized.startswith(prefix):
            return False
    # Root-level or docs/ Markdown only (not every *.md in the repo).
    if normalized.endswith(".md") and ("/" not in normalized or normalized.startswith("docs/")):
        return True
    name = PurePosixPath(normalized)
    for pattern in _DOCS_ONLY_PATTERNS:
        if fnmatch.fnmatch(normalized, pattern) or fnmatch.fnmatch(name.name, pattern):
            return True
    return False


def changed_files(base_ref: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base_ref}...HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
    if result.returncode != 0:
        msg = result.stderr.strip() or result.stdout.strip() or "git diff failed"
        raise RuntimeError(msg)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def pr_touches_code(changed: list[str]) -> bool:
    if not changed:
        return False
    return any(not _matches_docs_only(path) for path in changed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="", help="GITHUB_EVENT_NAME")
    parser.add_argument("--base", default="main", help="PR base branch name")
    args = parser.parse_args()

    touches = True if args.event != "pull_request" else pr_touches_code(changed_files(args.base))

    github_output = os.environ.get("GITHUB_OUTPUT", "")
    if github_output:
        with open(github_output, "a", encoding="utf-8") as handle:
            handle.write(f"code={'true' if touches else 'false'}\n")

    print("true" if touches else "false")
    # Exit 0 always: callers run under ``set -e`` and read ``code`` from GITHUB_OUTPUT.
    return 0


if __name__ == "__main__":
    sys.exit(main())
