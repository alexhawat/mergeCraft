#!/usr/bin/env python3
"""Select pytest nodes for tier-2 PR runs from changed paths (#1493)."""

from __future__ import annotations

import argparse
import subprocess
from pathlib import PurePosixPath


def _changed_files(base_ref: str) -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
        text=True,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def _tests_for_path(path: str) -> set[str]:
    p = PurePosixPath(path)
    if p.parts[:1] == ("tests",):
        return {path.replace("\\", "/")}
    if p.parts[:1] == ("src",) and p.suffix == ".py":
        module = "/".join(p.parts[1:]).removesuffix(".py")
        candidates = {
            f"tests/{module.replace('/', '/test_')}.py",
            f"tests/{'/'.join(p.parts[:2])}",
        }
        return {c for c in candidates if c.startswith("tests/")}
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
    if len(selected) <= 2 and files:
        print(args.fallback)
        return 0
    print(" ".join(sorted(selected)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
