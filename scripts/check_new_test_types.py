"""Type-check added test modules while existing test diagnostics are paid down."""

from __future__ import annotations

import os
import subprocess
import sys


def main() -> int:
    base_sha = os.environ["MERGECRAFT_TEST_TYPE_BASE"]
    names = subprocess.check_output(
        [
            "git",
            "diff",
            "--no-renames",
            "--diff-filter=A",
            "--name-only",
            "-z",
            f"{base_sha}...HEAD",
            "--",
            "tests/*.py",
        ]
    )
    paths = [os.fsdecode(name) for name in names.split(b"\0") if name]
    if not paths:
        print("No new Python test modules.")
        return 0
    return subprocess.run(["pyright", *paths], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
