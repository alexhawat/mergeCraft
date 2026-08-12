#!/usr/bin/env python3
"""Coverage ratchet floors for production-readiness W12.2 / punch-list #26.

Reads a ``coverage.json`` produced by ``pytest --cov --cov-report=json`` and
fails when global or critical-path floors drop below the locked thresholds.

Floors are set from a measured baseline (2026-08-11, ~70% global line) with a
small buffer so the gate fails on decreases without flaking on noise. Critical
paths listed in the punch list get their own line/branch floors.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Global line-coverage floor (coverage.py ``fail_under`` mirrors this).
GLOBAL_LINE_FLOOR = 65.0

# Critical-path floors (line %, branch %). Values are ratchet floors just
# under the 2026-08-11 measured baseline so decreases fail the gate.
MODULE_FLOORS: dict[str, tuple[float, float]] = {
    "utils/token.py": (15.0, 0.0),
    "utils/git_setup.py": (80.0, 80.0),
    "main.py": (60.0, 40.0),
}


def _pct(covered: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return 100.0 * covered / total


def _match_module(path: str, suffix: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(suffix) or f"/{suffix}" in normalized


def _aggregate_prefix(files: dict[str, Any], needle: str) -> tuple[float, float]:
    stmts = covered = branches = covered_b = 0
    for path, payload in files.items():
        if needle not in path.replace("\\", "/"):
            continue
        summary = payload["summary"]
        stmts += int(summary["num_statements"])
        covered += int(summary["covered_lines"])
        branches += int(summary.get("num_branches") or 0)
        covered_b += int(summary.get("covered_branches") or 0)
    return _pct(covered, stmts), _pct(covered_b, branches)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "coverage_json",
        nargs="?",
        default="coverage.json",
        type=Path,
        help="Path to coverage.py JSON report (default: coverage.json)",
    )
    args = parser.parse_args()
    if not args.coverage_json.is_file():
        print(f"coverage report missing: {args.coverage_json}", file=sys.stderr)
        return 2

    data = json.loads(args.coverage_json.read_text(encoding="utf-8"))
    totals = data["totals"]
    global_line = float(totals["percent_covered"])
    failures: list[str] = []

    if global_line + 1e-9 < GLOBAL_LINE_FLOOR:
        failures.append(f"global line coverage {global_line:.2f}% < floor {GLOBAL_LINE_FLOOR:.2f}%")

    files: dict[str, Any] = data["files"]
    for suffix, (line_floor, branch_floor) in MODULE_FLOORS.items():
        matched = [
            (path, payload["summary"])
            for path, payload in files.items()
            if _match_module(path, suffix)
        ]
        if not matched:
            failures.append(f"no coverage data for {suffix}")
            continue
        # Prefer the shortest matching path (exact module over similarly named).
        _path, summary = sorted(matched, key=lambda item: len(item[0]))[0]
        line_pct = float(summary["percent_covered"])
        branch_pct = _pct(
            int(summary.get("covered_branches") or 0),
            int(summary.get("num_branches") or 0),
        )
        if line_pct + 1e-9 < line_floor:
            failures.append(f"{suffix} line {line_pct:.1f}% < floor {line_floor:.1f}%")
        if branch_pct + 1e-9 < branch_floor:
            failures.append(f"{suffix} branch {branch_pct:.1f}% < floor {branch_floor:.1f}%")

    for label, needle, line_floor, branch_floor in (
        ("mcp/", "/mcp/", 55.0, 35.0),
        ("action/", "/action/", 35.0, 35.0),
    ):
        line_pct, branch_pct = _aggregate_prefix(files, needle)
        if line_pct + 1e-9 < line_floor:
            failures.append(f"{label} line {line_pct:.1f}% < floor {line_floor:.1f}%")
        if branch_pct + 1e-9 < branch_floor:
            failures.append(f"{label} branch {branch_pct:.1f}% < floor {branch_floor:.1f}%")

    if failures:
        print("coverage floor check FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(f"coverage floor check OK (global line {global_line:.2f}% ≥ {GLOBAL_LINE_FLOOR:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
