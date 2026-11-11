#!/usr/bin/env python3
"""Decide whether a PR touches the surface the privileged boundary proofs protect.

The egress filter, sandbox and UID-drop proofs need a disposable root Linux runner
and are slow to bootstrap, so the required ``privileged-proofs`` CI job runs them
only when the diff reaches code or tooling they cover. Any non-PR event, a diff
that cannot be read, and an empty diff all say "run": a proof that might matter
is never skipped by accident.

Usage: ``ci_touches_privileged_surface.py --event EVENT --base BRANCH`` writes
``run=true|false`` to ``$GITHUB_OUTPUT`` and prints it. Exit status is always 0.
"""

from __future__ import annotations

import argparse
import fnmatch
import os
import subprocess
import sys

# fnmatch patterns over repo-relative POSIX paths (``*`` crosses ``/``).
PRIVILEGED_PATTERNS: tuple[str, ...] = (
    "src/mergecraft/analyzers/sandbox.py",
    "src/mergecraft/analyzers/sandbox_failures.py",
    "src/mergecraft/analyzers/egress*.py",
    "src/mergecraft/analyzers/run.py",
    "src/mergecraft/analyzers/execution.py",
    "src/mergecraft/analyzers/detect.py",
    "src/mergecraft/analyzers/resolve.py",
    "src/mergecraft/analyzers/trust.py",
    "src/mergecraft/analyzers/trust_posture.py",
    "src/mergecraft/security/*",
    "src/mergecraft/utils/privilege.py",
    "docker/*",
    ".github/workflows/*",
    ".github/actions/*",
    "tests/analyzers/test_filtered_egress.py",
    "tests/analyzers/test_sandbox_execution.py",
    "tests/analyzers/test_trusted_uid_drop.py",
    "tests/security/test_analyzer_uid_drop.py",
    "scripts/ci_touches_privileged_surface.py",
    "Makefile",
    "pyproject.toml",
    "uv.lock",
)


def touches_privileged_surface(paths: list[str]) -> bool:
    """True when any path is covered by a privileged proof, or the diff is empty."""
    if not paths:
        return True
    for path in paths:
        normalized = path.replace("\\", "/").removeprefix("./")
        if any(fnmatch.fnmatchcase(normalized, pattern) for pattern in PRIVILEGED_PATTERNS):
            return True
    return False


def _changed_files(base: str) -> list[str] | None:
    for ref in (f"origin/{base}...HEAD", f"{base}...HEAD"):
        result = subprocess.run(
            ["git", "diff", "--name-only", ref], check=False, capture_output=True, text=True
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", default="")
    parser.add_argument("--base", default="main")
    args = parser.parse_args()
    run = True
    if args.event == "pull_request":
        changed = _changed_files(args.base)
        run = True if changed is None else touches_privileged_surface(changed)
    value = "true" if run else "false"
    output = os.environ.get("GITHUB_OUTPUT", "")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write(f"run={value}\n")
    print(value)
    return 0


if __name__ == "__main__":
    sys.exit(main())
