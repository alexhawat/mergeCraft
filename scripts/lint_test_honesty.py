#!/usr/bin/env python3
"""Fail on dishonest test patterns in the ``tests/`` tree.

Complements Ruff test-scoped rule S110 with AST checks for fixed
sleeps, flake masking, swallowed exceptions, conditional assertions, and
self-mocking. Existing violations are listed in ``test_honesty_baseline.json``;
new ones fail the gate unless suppressed with ``# honesty: allow <reason>``.

Module: scripts.lint_test_honesty
Depends: argparse, json, pathlib, subprocess, sys, test_honesty_visitors

Exports:
    load_baseline — read the committed baseline fingerprint set.
    filter_findings — drop baselined and allow-comment hits.
    check_test_honesty — return 0 when no new blocking findings remain.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, TextIO

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from test_honesty_visitors import (  # noqa: E402  # import after sys.path bootstrap
    HONESTY_RUFF_EXCLUDE,
    HonestyFinding,
    HonestyScanResult,
    scan_paths,
)

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"
BASELINE_PATH = REPO / "scripts" / "test_honesty_baseline.json"
RUFF_TEST_SELECT = "S110"


class BaselineFile(NamedTuple):
    """Parsed baseline."""

    fingerprints: frozenset[str]
    documented_count: int | None


def load_baseline(path: Path = BASELINE_PATH) -> BaselineFile:
    """Load baseline fingerprints from ``path``."""
    if not path.is_file():
        return BaselineFile(fingerprints=frozenset(), documented_count=None)
    data = json.loads(path.read_text(encoding="utf-8"))
    entries = data.get("fingerprints", [])
    if not isinstance(entries, list):
        raise ValueError("baseline fingerprints must be a list")
    fps = frozenset(str(item) for item in entries)
    documented = data.get("violation_count")
    return BaselineFile(fingerprints=fps, documented_count=documented)


def filter_findings(
    result: HonestyScanResult,
    baseline: BaselineFile,
) -> tuple[list[HonestyFinding], list[HonestyFinding]]:
    """Split findings into baselined (grandfathered) and new."""
    new: list[HonestyFinding] = []
    grandfathered: list[HonestyFinding] = []
    for finding in result.findings:
        if finding.fingerprint in baseline.fingerprints:
            grandfathered.append(finding)
        else:
            new.append(finding)
    return new, grandfathered


def run_ruff_test_honesty(*, repo: Path = REPO) -> int:
    """Run Ruff S110 on ``tests/`` (excluding checker fixtures); return exit code."""
    ruff = repo / ".venv-dev" / "bin" / "ruff"
    ruff_cmd = ["uv", "run", "ruff"] if not ruff.is_file() else [str(ruff)]
    cmd = [
        *ruff_cmd,
        "check",
        "tests",
        "--select",
        RUFF_TEST_SELECT,
        "--extend-exclude",
        HONESTY_RUFF_EXCLUDE,
    ]
    completed = subprocess.run(cmd, cwd=repo, check=False)
    return completed.returncode


def _print_findings(
    findings: list[HonestyFinding],
    *,
    label: str,
    stream: TextIO = sys.stderr,
) -> None:
    for finding in findings:
        level = "WARN" if finding.level == "warning" else "ERROR"
        print(
            f"test-honesty {label} {level} {finding.path}:{finding.line_no}: {finding.message}",
            file=stream,
        )


def check_test_honesty(
    targets: list[Path],
    *,
    repo: Path = REPO,
    baseline: BaselineFile | None = None,
    skip_ruff: bool = False,
) -> tuple[int, HonestyScanResult, list[HonestyFinding], list[HonestyFinding]]:
    """Return exit code and scan artifacts."""
    baseline = baseline or load_baseline()
    result = scan_paths(targets, repo=repo)
    new_findings, grandfathered = filter_findings(result, baseline)
    blocking_new = [f for f in new_findings if f.level == "error"]
    warning_new = [f for f in new_findings if f.level == "warning"]

    if warning_new:
        _print_findings(warning_new, label="new", stream=sys.stderr)
    if blocking_new:
        _print_findings(blocking_new, label="new", stream=sys.stderr)

    exit_code = 0
    if blocking_new:
        exit_code = 1
    if not skip_ruff:
        ruff_code = run_ruff_test_honesty(repo=repo)
        if ruff_code != 0:
            exit_code = 1

    return exit_code, result, new_findings, grandfathered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Files or directories (default: tests/).")
    parser.add_argument(
        "--skip-ruff",
        action="store_true",
        help="Only run the AST checker (used by unit tests).",
    )
    parser.add_argument(
        "--write-baseline",
        action="store_true",
        help="Rewrite the full baseline from the current tree (maintainer; never on drive-by PRs).",
    )
    parser.add_argument(
        "--prune-baseline",
        action="store_true",
        help="Drop stale baseline fingerprints that no longer match any finding.",
    )
    args = parser.parse_args(argv)

    if (args.write_baseline or args.prune_baseline) and args.paths:
        print(
            "test-honesty: --write-baseline/--prune-baseline require a full tests/ scan",
            file=sys.stderr,
        )
        return 2

    scan_targets = [Path(p) for p in args.paths] if args.paths else [TESTS]
    if not scan_targets and not TESTS.is_dir():
        print(f"missing tests tree: {TESTS}", file=sys.stderr)
        return 1

    baseline = load_baseline()
    result = scan_paths(scan_targets, repo=REPO)

    current_fps = {f.fingerprint for f in result.findings}

    if args.prune_baseline:
        kept = sorted(fp for fp in baseline.fingerprints if fp in current_fps)
        removed = len(baseline.fingerprints) - len(kept)
        payload = {"violation_count": len(kept), "fingerprints": kept}
        BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(
            f"pruned baseline: kept {len(kept)}, removed {removed} stale entries in {BASELINE_PATH}",
            file=sys.stderr,
        )
        return 0

    if args.write_baseline:
        fingerprints = sorted(current_fps)
        payload = {
            "violation_count": len(fingerprints),
            "fingerprints": fingerprints,
        }
        BASELINE_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {len(fingerprints)} baseline entries to {BASELINE_PATH}")
        return 0

    exit_code, _, new_findings, grandfathered = check_test_honesty(
        scan_targets,
        repo=REPO,
        baseline=baseline,
        skip_ruff=args.skip_ruff,
    )
    blocking_new = [f for f in new_findings if f.level == "error"]
    warnings_new = [f for f in new_findings if f.level == "warning"]
    print(
        "test-honesty summary: "
        f"{len(grandfathered)} baselined, "
        f"{len(blocking_new)} new error(s), "
        f"{len(warnings_new)} new warning(s)",
        file=sys.stderr,
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
