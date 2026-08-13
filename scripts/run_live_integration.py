#!/usr/bin/env python3
"""Run the live-provider integration slice (W4 / D9).

Encapsulates credential checks and per-provider pytest selection so the
Makefile stays a thin wrapper. ``MERGECRAFT_ALLOW_MISSING_LIVE_CREDS=1`` skips
the fail-loud check for local runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from mergecraft.integrations.live_providers import (  # noqa: E402
    live_pytest_paths,
    missing_live_credentials,
)

LIVE_PYTEST_MARKER = "live"


def main(argv: list[str] | None = None) -> int:
    _ = argv
    marker = os.environ.get("MERGECRAFT_LIVE_PYTEST_MARKER", LIVE_PYTEST_MARKER)
    if marker != LIVE_PYTEST_MARKER:
        print(
            f"unexpected MERGECRAFT_LIVE_PYTEST_MARKER={marker!r}; expected {LIVE_PYTEST_MARKER!r}",
            file=sys.stderr,
        )
        return 1
    provider = os.environ.get("MERGECRAFT_LIVE_PROVIDER") or None
    if os.environ.get("MERGECRAFT_ALLOW_MISSING_LIVE_CREDS") != "1":
        missing = missing_live_credentials(provider)
        if missing:
            names = " ".join(missing)
            print(
                f"missing live credentials: {names} "
                "(set secrets or MERGECRAFT_ALLOW_MISSING_LIVE_CREDS=1 for local)",
                file=sys.stderr,
            )
            return 1

    paths = live_pytest_paths(provider)
    uv = shutil.which("uv") or "uv"
    cmd = [
        uv,
        "run",
        "pytest",
        *paths,
        "-v",
        "--tb=short",
        "--strict-markers",
        "-m",
        marker,
    ]
    jobs = os.environ.get("MERGECRAFT_PYTEST_JOBS", "auto")
    if jobs and jobs != "0":
        cmd.extend(["-n", jobs])
    seed = os.environ.get("MERGECRAFT_PYTEST_RANDOM_SEED", "424242")
    cmd.append(f"--randomly-seed={seed}")
    return subprocess.run(cmd, cwd=REPO_ROOT, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
