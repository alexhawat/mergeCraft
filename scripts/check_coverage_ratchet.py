#!/usr/bin/env python3
"""Coverage ratchet: enforce ``fail_under`` and require deliberate floor bumps.

Fails when measured line coverage drops below the floor in ``pyproject.toml``
(``[tool.coverage.report] fail_under``). Also fails when coverage exceeds the
floor by more than a fixed margin without bumping that floor — the bump is a
deliberate commit, not an automatic rewrite.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

# Allow coverage to rise this many points above ``fail_under`` before the gate
# forces a deliberate floor bump in ``pyproject.toml``.
DEFAULT_MARGIN = 5.0


def _fail_under_from_pyproject(repo_root: Path | None = None) -> float:
    cfg_path = Path(__file__).resolve().parent / "coverage_config.py"
    spec = importlib.util.spec_from_file_location("coverage_config", cfg_path)
    if spec is None or spec.loader is None:
        msg = f"could not load coverage config: {cfg_path}"
        raise ImportError(msg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.fail_under_from_pyproject(repo_root)


def _percent_covered(report: Path) -> float:
    if not report.is_file():
        msg = f"coverage report missing: {report}"
        raise FileNotFoundError(msg)
    data: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
    return float(data["totals"]["percent_covered"])


def check_coverage_ratchet(
    report: Path | str,
    *,
    floor: float | None = None,
    margin: float = DEFAULT_MARGIN,
    repo_root: Path | None = None,
) -> int:
    """Return 0 when coverage is within ``[floor, floor + margin]``; 1 otherwise."""
    report_path = Path(report)
    resolved_floor = floor if floor is not None else _fail_under_from_pyproject(repo_root)
    measured = _percent_covered(report_path)
    ceiling = resolved_floor + margin
    failures: list[str] = []

    if measured + 1e-9 < resolved_floor:
        failures.append(
            f"line coverage {measured:.2f}% < floor {resolved_floor:.2f}% "
            f"(see [tool.coverage.report] fail_under in pyproject.toml)"
        )
    elif measured > ceiling + 1e-9:
        failures.append(
            f"line coverage {measured:.2f}% exceeds floor {resolved_floor:.2f}% "
            f"by more than {margin:.2f} points (ceiling {ceiling:.2f}%) — "
            "bump fail_under in pyproject.toml in a deliberate commit"
        )

    if failures:
        print("coverage ratchet FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(f"coverage ratchet OK ({measured:.2f}% within [{resolved_floor:.2f}%, {ceiling:.2f}%])")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "coverage_json",
        nargs="?",
        default="coverage.json",
        type=Path,
        help="Path to coverage.py JSON report (default: coverage.json)",
    )
    parser.add_argument(
        "--margin",
        type=float,
        default=DEFAULT_MARGIN,
        help=f"Points above fail_under before a bump is required (default: {DEFAULT_MARGIN})",
    )
    args = parser.parse_args(argv)
    try:
        return check_coverage_ratchet(args.coverage_json, margin=args.margin)
    except (FileNotFoundError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"coverage ratchet error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
