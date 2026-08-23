#!/usr/bin/env python3
"""Coverage delta vs base branch for #432 / D6.

Compares a head ``coverage.json`` (merge result or push) against a base-branch
report so CI can distinguish an inherited floor breach from a drop caused by the
change under review.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, NamedTuple

# When the base is already at the floor, a head breach this many points or more
# below the floor is treated as inherited cumulative drift rather than a marginal
# regression caused solely by the current change.
INHERITED_BREACH_MARGIN = 1.0


def _fail_under_from_pyproject() -> float:
    cfg_path = Path(__file__).resolve().parent / "coverage_config.py"
    spec = importlib.util.spec_from_file_location("coverage_config", cfg_path)
    if spec is None or spec.loader is None:
        msg = f"could not load coverage config: {cfg_path}"
        raise ImportError(msg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.fail_under_from_pyproject()


def _percent_covered(report: Path) -> float:
    if not report.is_file():
        msg = f"coverage report missing: {report}"
        raise FileNotFoundError(msg)
    data: dict[str, Any] = json.loads(report.read_text(encoding="utf-8"))
    return float(data["totals"]["percent_covered"])


class CoverageDeltaResult(NamedTuple):
    """Attribution for a head report measured against the base branch."""

    head_percent: float
    base_percent: float
    floor: float
    delta: float
    inherited: bool
    caused_by_change: bool
    message: str


def compare_to_base(head: Path, base: Path, *, floor: float | None = None) -> CoverageDeltaResult:
    """Compare head coverage to base and classify inherited vs caused drops."""
    resolved_floor = floor if floor is not None else _fail_under_from_pyproject()
    head_percent = _percent_covered(head)
    base_percent = _percent_covered(base)
    delta = head_percent - base_percent
    breach_depth = resolved_floor - head_percent

    if base_percent + 1e-9 < resolved_floor:
        return CoverageDeltaResult(
            head_percent=head_percent,
            base_percent=base_percent,
            floor=resolved_floor,
            delta=delta,
            inherited=True,
            caused_by_change=False,
            message=(
                f"inherited drop: base branch {base_percent:.2f}% is below floor "
                f"{resolved_floor:.2f}% (head {head_percent:.2f}%, delta {delta:+.2f}pp)"
            ),
        )

    if head_percent + 1e-9 < resolved_floor and breach_depth + 1e-9 >= INHERITED_BREACH_MARGIN:
        return CoverageDeltaResult(
            head_percent=head_percent,
            base_percent=base_percent,
            floor=resolved_floor,
            delta=delta,
            inherited=True,
            caused_by_change=False,
            message=(
                f"inherited drop: head {head_percent:.2f}% is {breach_depth:.2f}pp below floor "
                f"{resolved_floor:.2f}% vs base {base_percent:.2f}%"
            ),
        )

    if head_percent + 1e-9 < base_percent:
        return CoverageDeltaResult(
            head_percent=head_percent,
            base_percent=base_percent,
            floor=resolved_floor,
            delta=delta,
            inherited=False,
            caused_by_change=True,
            message=(
                f"caused drop: head {head_percent:.2f}% vs base {base_percent:.2f}% "
                f"(delta {delta:+.2f}pp)"
            ),
        )

    return CoverageDeltaResult(
        head_percent=head_percent,
        base_percent=base_percent,
        floor=resolved_floor,
        delta=delta,
        inherited=False,
        caused_by_change=False,
        message=(
            f"coverage delta OK: head {head_percent:.2f}% vs base {base_percent:.2f}% "
            f"(delta {delta:+.2f}pp, floor {resolved_floor:.2f}%)"
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "head",
        nargs="?",
        default="coverage.json",
        type=Path,
        help="Head/merge coverage report (default: coverage.json)",
    )
    parser.add_argument(
        "--base",
        required=True,
        type=Path,
        help="Base-branch coverage report to compare against",
    )
    args = parser.parse_args(argv)

    result = compare_to_base(args.head, args.base)
    print(result.message)
    if result.inherited:
        print(
            "Coverage gate: inherited floor breach on the base branch — "
            "fix the base or bump coverage on the base branch before this PR.",
            file=sys.stderr,
        )
        return 1
    if result.caused_by_change and result.head_percent + 1e-9 < result.floor:
        print(
            f"Coverage gate: caused drop — head {result.head_percent:.2f}% is below floor "
            f"{result.floor:.2f}% and regressed from base {result.base_percent:.2f}%.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
