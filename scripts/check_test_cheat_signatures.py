#!/usr/bin/env python3
"""Flag tautological test patterns in the ``tests/`` tree (D16).

Detects:

* ``getattr(mod, "NAME", <literal>)`` compared for equality to the same literal.
* ``evaluate_decision_case(..., answer=case.expected_answer)`` when the only
  assertion on the result is ``assert result.passed``.
* ``verdict != "auto_merge"`` comparisons (warning only).

Walks top-level functions, class methods, and nested function bodies.

By default the gate **blocks** (exit 1 on errors). Pass ``--advisory`` to print
findings but exit 0 so grandfathered sites do not block ``make lint``.

Module: scripts.check_test_cheat_signatures
Depends: argparse, pathlib, sys, typing, ast_cheat_visitors

Exports:
    scan_file — AST scan one Python file.
    scan_paths — scan many files and return errors and warnings.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TextIO

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
from ast_cheat_visitors import ScanResult, scan_paths  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
TESTS = REPO / "tests"


def _print_findings(result: ScanResult, *, stream: TextIO = sys.stderr) -> None:
    for finding in [*result.errors, *result.warnings]:
        prefix = "ERROR" if finding.level == "error" else "WARN"
        print(
            f"cheat-signature {prefix} {finding.path}:{finding.line_no}: "
            f"{finding.kind}: {finding.detail}",
            file=stream,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", help="Files or directories (default: tests/).")
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Print findings but exit 0 (opt-out from the default blocking gate).",
    )
    args = parser.parse_args(argv)

    scan_targets = [Path(p) for p in args.paths] if args.paths else [TESTS]
    if not scan_targets and not TESTS.is_dir():
        print(f"missing tests tree: {TESTS}", file=sys.stderr)
        return 1

    result = scan_paths(scan_targets, repo=REPO)
    all_findings = [*result.errors, *result.warnings]
    if all_findings:
        _print_findings(result)

    blocking = [finding for finding in all_findings if finding.level == "error"]
    warnings = [finding for finding in all_findings if finding.level == "warning"]

    if blocking and not args.advisory:
        print(
            f"cheat-signature: {len(blocking)} error(s), {len(warnings)} warning(s)",
            file=sys.stderr,
        )
        return 1

    if warnings:
        print(f"cheat-signature: {len(warnings)} warning(s)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
