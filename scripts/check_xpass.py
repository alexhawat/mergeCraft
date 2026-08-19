#!/usr/bin/env python3
"""Fail when pytest reports unexpected xpasses on the allowed test tree.

``xfail(strict=False)`` tests that pass (XPASS) are leftover RED markers.
This ratchet exits 1 when any XPASS remains outside the morning-plan D6
exclusion list. D6 xpasses are counted and printed, then ignored.

Parses pytest ``-rX`` / ``-ra`` terminal output (``XPASS nodeid - reason``
lines). Pass ``--from-log`` for a cheap post-test parse (W7); with no log,
runs the unit suite so the gate is RED today while allowed-tree xpasses exist.

Module: scripts.check_xpass
Depends: argparse, pathlib, subprocess, sys, typing

Exports:
    D6_TEST_PATHS — morning-plan test files excluded from the fail condition.
    is_d6_nodeid — True when a pytest nodeid lives on a D6 path.
    parse_xpass_log — extract XPASS records from pytest terminal output.
    check_xpass — return 0 iff allowed-tree xpass count is 0.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple, TextIO

REPO = Path(__file__).resolve().parents[1]

# Morning-plan test files this program must not clean up (D6). Inventory may
# still count them; they do not fail the gate.
D6_TEST_PATHS: frozenset[str] = frozenset(
    {
        "tests/agents/test_codex_custom_provider.py",
        "tests/analyzers/test_scope.py",
        "tests/cli/test_auth_logfire_cmd.py",
        "tests/cli/test_gha_cmd.py",
        "tests/cli/test_gha_failure_outputs.py",
        "tests/evals/test_live_context.py",
        "tests/mcp/test_check_runs.py",
        "tests/mcp/test_git_tool.py",
        "tests/mcp/test_labels.py",
        "tests/mcp/test_submit_review_verdict.py",
        "tests/mcp/test_upload.py",
        "tests/review/test_terminal_verdict_policy.py",
    }
)

_PYTEST_SELECTOR = ("tests", "-m", "not integration", "--strict-markers", "-q", "--tb=no", "-rX")


class XpassRecord(NamedTuple):
    """One pytest XPASS line."""

    nodeid: str
    reason: str

    @property
    def d6(self) -> bool:
        """Return True when this xpass is on a D6-forbidden test path."""
        return is_d6_nodeid(self.nodeid)


class XpassInventory(NamedTuple):
    """Parsed xpass set plus D6 / allowed splits."""

    records: tuple[XpassRecord, ...]

    @property
    def total(self) -> int:
        """Return the number of XPASS lines parsed."""
        return len(self.records)

    @property
    def d6_records(self) -> tuple[XpassRecord, ...]:
        """Return xpasses on D6 paths (counted, not failing)."""
        return tuple(record for record in self.records if record.d6)

    @property
    def allowed_records(self) -> tuple[XpassRecord, ...]:
        """Return xpasses this program is allowed to promote (W6)."""
        return tuple(record for record in self.records if not record.d6)

    @property
    def d6_count(self) -> int:
        """Return the D6-excluded xpass count."""
        return len(self.d6_records)

    @property
    def allowed_count(self) -> int:
        """Return the allowed-tree xpass count (the fail condition)."""
        return len(self.allowed_records)


def is_d6_nodeid(nodeid: str) -> bool:
    """Return True when ``nodeid`` belongs to a D6-forbidden test file.

    Args:
        nodeid: Pytest nodeid (``path::test`` or ``path::test[param]``).

    Returns:
        True when the path component is in ``D6_TEST_PATHS``.
    """
    path = nodeid.split("::", 1)[0].replace("\\", "/")
    return path in D6_TEST_PATHS


def parse_xpass_log(text: str) -> XpassInventory:
    """Extract XPASS records from pytest ``-rX`` / ``-ra`` terminal output.

    Args:
        text: Captured pytest stdout+stderr.

    Returns:
        Inventory of every ``XPASS`` line, D6-tagged.
    """
    records: list[XpassRecord] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("XPASS "):
            continue
        rest = line[len("XPASS ") :]
        nodeid, sep, reason = rest.partition(" - ")
        nodeid = nodeid.strip()
        if not nodeid:
            continue
        records.append(XpassRecord(nodeid=nodeid, reason=reason if sep else ""))
    return XpassInventory(records=tuple(records))


def check_xpass(inventory: XpassInventory, *, stream: TextIO | None = None) -> int:
    """Return 0 when allowed-tree xpass count is 0; 1 otherwise.

    Args:
        inventory: Parsed xpass set.
        stream: Output stream (default ``sys.stderr``).

    Returns:
        Process exit code (0 ok, 1 allowed-tree xpasses remain).
    """
    out: TextIO = sys.stderr if stream is None else stream
    allowed = inventory.allowed_records
    summary = (
        f"{inventory.allowed_count} allowed-tree xpassed "
        f"({inventory.total} total, {inventory.d6_count} D6-excluded)"
    )
    if not allowed:
        print(f"xpass-check OK: {summary}", file=out)
        return 0

    print(f"xpass-check FAILED: {summary}", file=out)
    for record in allowed:
        print(f"  {record.nodeid}", file=out)
    return 1


def _run_pytest(repo_root: Path) -> str:
    """Run the unit suite and return combined stdout+stderr."""
    cmd = [sys.executable, "-m", "pytest", *_PYTEST_SELECTOR]
    completed = subprocess.run(
        cmd,
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    return (completed.stdout or "") + (completed.stderr or "")


def main(argv: list[str] | None = None) -> int:
    """CLI entry: parse a pytest log or run the unit suite, then ratchet.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        0 when allowed-tree xpass is 0; 1 when xpasses remain; 2 on usage/IO error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-log",
        metavar="PATH",
        help="Pytest terminal log to parse ('-' = stdin). Omit to run the unit suite.",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=REPO,
        help="Repo root when running pytest (default: parent of scripts/)",
    )
    args = parser.parse_args(argv)

    try:
        if args.from_log is None:
            text = _run_pytest(Path(args.repo_root))
        elif args.from_log == "-":
            text = sys.stdin.read()
        else:
            text = Path(args.from_log).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"xpass-check error: {exc}", file=sys.stderr)
        return 2

    inventory = parse_xpass_log(text)
    return check_xpass(inventory)


if __name__ == "__main__":
    raise SystemExit(main())
