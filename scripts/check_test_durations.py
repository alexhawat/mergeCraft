#!/usr/bin/env python3
"""Guard: ``.test_durations`` must cover collected test ids and stay committable.

Least-duration sharding treats a case with no recorded duration as average, so a
stale file silently unbalances the CI shards. This collects the unit lane's
selection (nothing executes) and fails when under 95% of ids have a timing, or
when any recorded id carries a security-scanner suppression marker (those ids
would trip the repo's own self-silencing analyzer; give such parametrized cases
explicit short ``ids=``).

Module: scripts.check_test_durations
Depends: json, subprocess, mergecraft.analyzers

Exports:
    unsafe_ids — ids that embed a security-scanner suppression marker.
    coverage — fraction of ids with a recorded duration.
    main — CLI entry (``make test-durations-check``).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from mergecraft.analyzers.self_silencing.markers import scan_added_markers

MIN_COVERAGE = 0.95
ROOT = Path(__file__).resolve().parents[1]
_DURATIONS = ROOT / ".test_durations"


def unsafe_ids(ids: list[str]) -> list[str]:
    """Return ids carrying a security-scanner suppression marker."""
    bad: list[str] = []
    for node_id in ids:
        diff = "diff --git a/f.py b/f.py\n--- a/f.py\n+++ b/f.py\n@@ -0,0 +1 @@\n+" + node_id + "\n"
        if any(hit.security for hit in scan_added_markers(diff)):
            bad.append(node_id)
    return bad


def coverage(ids: set[str], known: set[str]) -> float:
    """Return the fraction of ``ids`` present in ``known``."""
    return len(ids & known) / len(ids) if ids else 0.0


def collect_unit_lane_ids() -> set[str]:
    """Collect (never run) the ids the unit lane selects."""
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
    if proc.returncode != 0:
        sys.exit(f"collection failed:\n{proc.stdout[-800:]}\n{proc.stderr[-800:]}")
    return {line.strip() for line in proc.stdout.splitlines() if "::" in line}


def main() -> int:
    """Check marker hygiene and collected-id coverage of ``.test_durations``."""
    known = set(json.loads(_DURATIONS.read_text(encoding="utf-8")))
    bad = unsafe_ids(sorted(known))
    if bad:
        print(f"{len(bad)} recorded ids embed a security-scanner suppression marker:")
        print("\n".join(f"  {node_id[:140]}" for node_id in bad[:10]))
        return 1
    ids = collect_unit_lane_ids()
    ratio = coverage(ids, known)
    print(f".test_durations covers {len(ids & known)}/{len(ids)} collected ids ({ratio:.1%})")
    if ratio < MIN_COVERAGE:
        print("Run `make test-durations` and commit the file.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
