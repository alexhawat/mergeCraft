#!/usr/bin/env python3
"""Coverage ratchet: enforce ``fail_under`` and require deliberate floor bumps.

Fails when measured line coverage drops below the floor in ``pyproject.toml``
(``[tool.coverage.report] fail_under``). Compares the declared floor to the
merge-base ``pyproject.toml`` value so lowering ``fail_under`` without a
deliberate baseline commit fails the gate.

When coverage exceeds the floor by more than a fixed margin, the default mode
emits a **warning** (exit 0). Pass ``--hard-ceiling`` to fail instead.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

# Allow coverage to rise this many points above ``fail_under`` before the gate
# nudges a deliberate floor bump in ``pyproject.toml``.
DEFAULT_MARGIN = 5.0
_EPS = 1e-9
_COVERAGE_CONFIG_PATH = Path(__file__).resolve().parent / "coverage_config.py"


def _load_coverage_config_module() -> Any:
    spec = importlib.util.spec_from_file_location("coverage_config", _COVERAGE_CONFIG_PATH)
    if spec is None or spec.loader is None:
        msg = f"could not load coverage config: {_COVERAGE_CONFIG_PATH}"
        raise ImportError(msg)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _fail_under_from_pyproject(repo_root: Path | None = None) -> float:
    return _load_coverage_config_module().fail_under_from_pyproject(repo_root)


def _repo_root(repo_root: Path | None) -> Path:
    if repo_root is not None:
        return repo_root
    return _load_coverage_config_module().repo_root()


def _fail_under_from_git_ref(repo_root: Path, ref: str) -> float | None:
    result = subprocess.run(
        ["git", "show", f"{ref}:pyproject.toml"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    data = tomllib.loads(result.stdout)
    floor = data.get("tool", {}).get("coverage", {}).get("report", {}).get("fail_under")
    if floor is None:
        return None
    return float(floor)


def _merge_base_ref(repo_root: Path, *, base_ref: str | None = None) -> str | None:
    if base_ref is not None:
        return base_ref
    base_branch = os.environ.get("GITHUB_BASE_REF", "pre-0.0.1")
    remote_base = f"origin/{base_branch}"
    result = subprocess.run(
        ["git", "merge-base", "HEAD", remote_base],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0 or not result.stdout.strip():
        return None
    return result.stdout.strip()


def _in_ci() -> bool:
    """Return True when running under CI (local ``CI=true`` or GitHub Actions)."""
    ci = os.environ.get("CI", "").lower()
    actions = os.environ.get("GITHUB_ACTIONS", "").lower()
    return ci in {"1", "true", "yes"} or actions in {"1", "true", "yes"}


def _fail_under_from_merge_base(
    repo_root: Path | None = None,
    *,
    allow_no_merge_base: bool = False,
    base_ref: str | None = None,
) -> tuple[float | None, str | None]:
    root = _repo_root(repo_root)
    base_branch = os.environ.get("GITHUB_BASE_REF", "pre-0.0.1")
    remote_base = f"origin/{base_branch}"
    merge_base = _merge_base_ref(root, base_ref=base_ref)
    if merge_base is None:
        detail = (
            f"merge-base lookup failed for HEAD vs {base_ref or remote_base} "
            f"(git merge-base returned non-zero or empty output)"
        )
        if _in_ci() and not allow_no_merge_base:
            return None, detail
        return None, None
    floor = _fail_under_from_git_ref(root, merge_base)
    if floor is None:
        detail = f"merge-base {merge_base} has no [tool.coverage.report] fail_under"
        if _in_ci() and not allow_no_merge_base:
            return None, detail
        return None, None
    return floor, None


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
    hard_ceiling: bool = False,
    allow_no_merge_base: bool = False,
    base_ref: str | None = None,
) -> int:
    """Return 0 when coverage is acceptable; 1 on hard failures."""
    report_path = Path(report)
    root = _repo_root(repo_root)
    declared_floor = _fail_under_from_pyproject(root)
    resolved_floor = floor if floor is not None else declared_floor
    measured = _percent_covered(report_path)
    ceiling = resolved_floor + margin
    failures: list[str] = []
    warnings: list[str] = []

    baseline_floor, merge_base_error = _fail_under_from_merge_base(
        root,
        allow_no_merge_base=allow_no_merge_base,
        base_ref=base_ref,
    )
    if merge_base_error is not None:
        failures.append(merge_base_error)
    elif baseline_floor is not None and declared_floor + _EPS < baseline_floor:
        failures.append(
            f"fail_under {declared_floor:.2f}% is below merge-base floor "
            f"{baseline_floor:.2f}% — bump fail_under only in a deliberate commit"
        )

    if measured + _EPS < resolved_floor:
        failures.append(
            f"line coverage {measured:.2f}% < floor {resolved_floor:.2f}% "
            f"(see [tool.coverage.report] fail_under in pyproject.toml)"
        )
    elif measured > ceiling + _EPS:
        message = (
            f"line coverage {measured:.2f}% exceeds floor {resolved_floor:.2f}% "
            f"by more than {margin:.2f} points (ceiling {ceiling:.2f}%) — "
            "consider bumping fail_under in pyproject.toml in a deliberate commit"
        )
        if hard_ceiling:
            failures.append(message)
        else:
            warnings.append(message)

    if failures:
        print("coverage ratchet FAILED:", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1

    for item in warnings:
        print(f"coverage ratchet WARNING: {item}", file=sys.stderr)

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
        help=f"Points above fail_under before a bump is suggested (default: {DEFAULT_MARGIN})",
    )
    parser.add_argument(
        "--hard-ceiling",
        action="store_true",
        help="Fail (instead of warn) when measured exceeds floor + margin",
    )
    parser.add_argument(
        "--allow-no-merge-base",
        action="store_true",
        help="Skip merge-base ratchet when git history is unavailable (tests only).",
    )
    parser.add_argument(
        "--base-ref",
        metavar="REF",
        help=(
            "Git ref for merge-base floor comparison "
            "(default: merge-base of HEAD and origin/$GITHUB_BASE_REF)."
        ),
    )
    args = parser.parse_args(argv)
    try:
        return check_coverage_ratchet(
            args.coverage_json,
            margin=args.margin,
            hard_ceiling=args.hard_ceiling,
            allow_no_merge_base=args.allow_no_merge_base,
            base_ref=args.base_ref,
        )
    except (FileNotFoundError, KeyError, json.JSONDecodeError, ValueError) as exc:
        print(f"coverage ratchet error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
