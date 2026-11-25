"""Type-check added test modules while existing test diagnostics are paid down.

The base is ``MERGECRAFT_TEST_TYPE_BASE`` when set (pull-request CI passes the
base commit), else ``origin/main``. Added modules count whether committed,
staged or untracked, so the local gate covers a test before it is committed.
"""

from __future__ import annotations

import os
import subprocess
import sys

_BASE_ENV = "MERGECRAFT_TEST_TYPE_BASE"
_DEFAULT_BASE = "origin/main"
_TEST_MODULES = "tests/*.py"


def _merge_base(base: str) -> str | None:
    """Return the commit ``HEAD`` forked from ``base`` at, or ``None``."""
    result = subprocess.run(
        ["git", "merge-base", base, "HEAD"], capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _added_test_modules(fork_point: str) -> list[str]:
    """Return test modules added since ``fork_point``, including untracked ones."""
    added = subprocess.check_output(
        [
            "git",
            "diff",
            "--no-renames",
            "--diff-filter=A",
            "--name-only",
            "-z",
            fork_point,
            "--",
            _TEST_MODULES,
        ]
    )
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z", "--", _TEST_MODULES]
    )
    names = (added + untracked).split(b"\0")
    return sorted({os.fsdecode(name) for name in names if name})


def main() -> int:
    base = os.environ.get(_BASE_ENV) or _DEFAULT_BASE
    fork_point = _merge_base(base)
    if fork_point is None:
        print(
            f"check_new_test_types: cannot find where HEAD forked from {base!r}. "
            f"Fetch it, or set {_BASE_ENV} to the commit to compare against.",
            file=sys.stderr,
        )
        return 2
    paths = _added_test_modules(fork_point)
    if not paths:
        print("No new Python test modules.")
        return 0
    return subprocess.run(["pyright", *paths], check=False).returncode


if __name__ == "__main__":
    sys.exit(main())
