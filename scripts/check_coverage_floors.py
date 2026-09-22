#!/usr/bin/env python3
"""Coverage ratchet floors for production-readiness W12.2 / punch-list #26.

Reads a ``coverage.json`` produced by ``pytest --cov --cov-report=json`` and
fails when global or critical-path floors drop below the locked thresholds.

Floors are set from a measured baseline (2026-09-22, post coverage-floor
re-baseline). Module floors use a 2-point buffer on line and branch. Prefix
aggregates use measured_line - 2 and measured_branch - 3 so branch coverage
has extra headroom on large trees without weakening the line gate.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any


def _fail_under_from_pyproject() -> float:
    cfg_path = Path(__file__).resolve().parent / "coverage_config.py"
    spec = importlib.util.spec_from_file_location("coverage_config", cfg_path)
    if spec is None or spec.loader is None:
        msg = f"could not load coverage config: {cfg_path}"
        raise ImportError(msg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.fail_under_from_pyproject()


# Critical-path floors (line %, branch %). Values are measured - 2 on
# 2026-09-22 @ wave/coverage-rebaseline (HEAD d04e6b5d).
MODULE_FLOORS: dict[str, tuple[float, float]] = {
    "utils/token.py": (90.7, 86.2),
    "utils/git_setup.py": (92.0, 86.7),
    "main.py": (86.1, 76.3),
}

# Prefix aggregates (line %, branch %). Line floors are measured - 2; branch
# floors are measured - 3 (extra headroom vs module floors). Branch floors for
# security/, analyzers/, agents/, and review/ remain ≥ 60 per D11.
PREFIX_FLOORS: tuple[tuple[str, str, float, float], ...] = (
    ("mcp/", "/mcp/", 82.1, 67.5),
    ("action/", "/action/", 90.4, 83.8),
    ("security/", "/security/", 86.5, 75.5),
    ("analyzers/", "/analyzers/", 83.3, 70.2),
    ("agents/", "/agents/", 85.8, 74.6),
    ("review/", "/review/", 85.9, 67.9),
)


def _pct(covered: int, total: int) -> float:
    if total <= 0:
        return 100.0
    return 100.0 * covered / total


def _match_module(path: str, suffix: str) -> bool:
    normalized = path.replace("\\", "/")
    return normalized.endswith(suffix) or f"/{suffix}" in normalized


def _aggregate_prefix(files: dict[str, Any], needle: str) -> tuple[float, float, bool]:
    stmts = covered = branches = covered_b = 0
    matched_any = False
    for path, payload in files.items():
        if needle not in path.replace("\\", "/"):
            continue
        matched_any = True
        summary = payload["summary"]
        stmts += int(summary["num_statements"])
        covered += int(summary["covered_lines"])
        branches += int(summary.get("num_branches") or 0)
        covered_b += int(summary.get("covered_branches") or 0)
    return _pct(covered, stmts), _pct(covered_b, branches), matched_any


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
    global_combined = float(totals["percent_covered"])
    global_floor = _fail_under_from_pyproject()
    failures: list[str] = []

    if global_combined + 1e-9 < global_floor:
        failures.append(
            f"global combined coverage {global_combined:.2f}% < floor {global_floor:.2f}%"
        )

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
        line_pct = _pct(
            int(summary["covered_lines"]),
            int(summary["num_statements"]),
        )
        branch_pct = _pct(
            int(summary.get("covered_branches") or 0),
            int(summary.get("num_branches") or 0),
        )
        if line_pct + 1e-9 < line_floor:
            failures.append(f"{suffix} line {line_pct:.1f}% < floor {line_floor:.1f}%")
        if branch_pct + 1e-9 < branch_floor:
            failures.append(f"{suffix} branch {branch_pct:.1f}% < floor {branch_floor:.1f}%")

    for label, needle, line_floor, branch_floor in PREFIX_FLOORS:
        line_pct, branch_pct, matched_any = _aggregate_prefix(files, needle)
        if not matched_any:
            failures.append(f"no coverage data for prefix {label}")
            continue
        if line_pct + 1e-9 < line_floor:
            failures.append(f"{label} line {line_pct:.1f}% < floor {line_floor:.1f}%")
        if branch_pct + 1e-9 < branch_floor:
            failures.append(f"{label} branch {branch_pct:.1f}% < floor {branch_floor:.1f}%")

    if failures:
        print("coverage floor check FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(f"coverage floor check OK (global combined {global_combined:.2f}% ≥ {global_floor:.2f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
