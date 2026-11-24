#!/usr/bin/env python3
"""Select pytest nodes for tier-2 PR runs from changed paths (#1493)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path, PurePosixPath


def _changed_files(base_ref: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        text=True,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


# A change to these can affect any test, so it is never narrowed.
_FULL_TREE_PATHS = frozenset({"pyproject.toml", "uv.lock"})
# Always run beside a narrowed selection, so the run is never empty when every
# selected test is deselected by the unit lane's markers.
_ANCHOR = "tests/ci/test_ci_select_tests.py"


def _tests_for_path(path: str) -> set[str]:
    p = PurePosixPath(path)
    if p.parts and p.parts[0] == "tests":
        # Pytest accepts collected modules here. Fixture reports and support files
        # are inputs, so passing them as explicit nodes aborts collection.
        return {p.as_posix()} if p.match("test_*.py") or p.match("*_test.py") else set()
    if len(p.parts) >= 3 and p.parts[:2] == ("src", "mergecraft") and p.suffix == ".py":
        rel = PurePosixPath(*p.parts[2:])
        test_file = PurePosixPath("tests") / rel.parent / f"test_{rel.stem}.py"
        return {test_file.as_posix()}
    if path.startswith(".github/workflows/") or path == "Makefile":
        return {"tests/ci"}
    return set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="main")
    parser.add_argument(
        "--fallback",
        default="tests",
        help="Node or directory when the change cannot be narrowed",
    )
    args = parser.parse_args()
    try:
        files = _changed_files(args.base)
    except subprocess.CalledProcessError:
        print(args.fallback)
        return 0
    if _FULL_TREE_PATHS.intersection(files):
        print(args.fallback)
        return 0
    selected: set[str] = set()
    for path in files:
        selected |= _tests_for_path(path)
    existing = {node for node in selected if Path(node).is_file() or Path(node).is_dir()}
    # No changed path maps to a test that exists: the change cannot be narrowed.
    if not existing:
        print(args.fallback)
        return 0
    # The result is a space-separated list, so a path with whitespace cannot be
    # carried in it; run everything rather than hand pytest half a path.
    if any(any(char.isspace() for char in node) for node in existing):
        print(args.fallback)
        return 0
    if Path(_ANCHOR).is_file():
        existing.add(_ANCHOR)
    print(" ".join(sorted(existing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
