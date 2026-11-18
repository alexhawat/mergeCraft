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


def _tests_for_path(path: str) -> set[str]:
    p = PurePosixPath(path)
    if p.parts and p.parts[0] == "tests":
        return {path.replace("\\", "/")}
    if len(p.parts) >= 3 and p.parts[:2] == ("src", "mergecraft") and p.suffix == ".py":
        rel = PurePosixPath(*p.parts[2:])
        test_file = PurePosixPath("tests") / rel.parent / f"test_{rel.stem}.py"
        return {test_file.as_posix()}
    if path.startswith(".github/workflows/") or path in {"Makefile", "pyproject.toml", "uv.lock"}:
        return {"tests/ci"}
    return set()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="main")
    parser.add_argument(
        "--fallback",
        default="tests",
        help="Node or directory when selection is empty",
    )
    args = parser.parse_args()
    try:
        files = _changed_files(args.base)
    except subprocess.CalledProcessError:
        print(args.fallback)
        return 0
    selected: set[str] = {"tests/conftest.py", "tests/ci"}
    for path in files:
        selected |= _tests_for_path(path)
    existing = {node for node in selected if Path(node).is_file() or Path(node).is_dir()}
    # Nothing beyond the always-on seeds: the change cannot be narrowed.
    if len(existing) <= 2 and files:
        print(args.fallback)
        return 0
    # The result is a space-separated list, so a path with whitespace cannot be
    # carried in it; run everything rather than hand pytest half a path.
    if any(any(char.isspace() for char in node) for node in existing):
        print(args.fallback)
        return 0
    print(" ".join(sorted(existing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
