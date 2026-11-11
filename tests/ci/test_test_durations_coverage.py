"""``.test_durations`` must cover most collected unit-lane ids (#1364).

Least-duration sharding treats a case with no recorded duration as average, so a
stale file silently unbalances the CI shards. This collects the unit lane's
selection (no test is executed) and fails when under 95% of ids have a timing.
Refresh with ``make test-durations``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MIN_COVERAGE = 0.95
ROOT = Path(__file__).resolve().parents[2]


def test_durations_file_covers_collected_unit_lane_ids() -> None:
    known = set(json.loads((ROOT / ".test_durations").read_text(encoding="utf-8")))
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "--collect-only",
            "-q",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "-m",
            "not integration and not coverage",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    ids = {line.strip() for line in proc.stdout.splitlines() if "::" in line}
    assert ids, proc.stdout[-500:] + proc.stderr[-500:]
    covered = len(ids & known)
    ratio = covered / len(ids)
    assert ratio >= MIN_COVERAGE, (
        f".test_durations covers {covered}/{len(ids)} collected ids ({ratio:.1%}); "
        "run `make test-durations` and commit the file"
    )
