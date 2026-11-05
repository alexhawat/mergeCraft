#!/usr/bin/env python3
"""Exit 0 when the PR diff touches the reviewer surface (#1164)."""

from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="main")
    args = parser.parse_args()
    diff = subprocess.check_output(
        ["git", "diff", "--name-only", f"origin/{args.base}...HEAD"],
        text=True,
    )
    paths = [line.strip() for line in diff.splitlines() if line.strip()]
    from mergecraft.evals.rescore_delta import touches_reviewer_surface

    return 0 if touches_reviewer_surface(paths) else 1


if __name__ == "__main__":
    sys.exit(main())
