#!/usr/bin/env python3
"""Fail when pytest reports unexpected xpasses on the allowed test tree.

``xfail(strict=False)`` tests that pass (XPASS) are leftover RED markers.
This ratchet exits 1 when any XPASS remains.

Parses pytest ``-rX`` / ``-ra`` terminal output (``XPASS nodeid - reason``
lines) from a log file passed via ``--from-log``. The live gate runs inside
the pytest session via the conftest ``pytest_sessionfinish`` hook.

Module: scripts.check_xpass
Depends: argparse, pathlib, sys, typing

Exports:
    parse_xpass_log — extract XPASS records from pytest terminal output.
    check_xpass — return 0 iff xpass count is 0.
    main — CLI entry.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import NamedTuple, TextIO

REPO = Path(__file__).resolve().parents[1]


class XpassRecord(NamedTuple):
    """One pytest XPASS line."""

    nodeid: str
    reason: str


class XpassInventory(NamedTuple):
    """Parsed xpass set."""

    records: tuple[XpassRecord, ...]

    @property
    def total(self) -> int:
        """Return the number of XPASS lines parsed."""
        return len(self.records)

    @property
    def failing_records(self) -> tuple[XpassRecord, ...]:
        """Return every parsed XPASS line (all are gate failures)."""
        return self.records

    @property
    def failing_count(self) -> int:
        """Return the number of XPASS lines (the fail condition)."""
        return len(self.records)


def parse_xpass_log(text: str) -> XpassInventory:
    """Extract XPASS records from pytest ``-rX`` / ``-ra`` terminal output.

    Args:
        text: Captured pytest stdout+stderr.

    Returns:
        Inventory of every ``XPASS`` line.
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
    """Return 0 when xpass count is 0; 1 otherwise.

    Args:
        inventory: Parsed xpass set.
        stream: Output stream (default ``sys.stderr``).

    Returns:
        Process exit code (0 ok, 1 xpasses remain).
    """
    out: TextIO = sys.stderr if stream is None else stream
    records = inventory.failing_records
    summary = f"{inventory.failing_count} xpassed ({inventory.total} total)"
    if not records:
        print(f"xpass-check OK: {summary}", file=out)
        return 0

    print(f"xpass-check FAILED: {summary}", file=out)
    for record in records:
        print(f"  {record.nodeid}", file=out)
    return 1


def main(argv: list[str] | None = None) -> int:
    """CLI entry: parse a pytest log file, then ratchet.

    Args:
        argv: Argument vector (defaults to ``sys.argv[1:]``).

    Returns:
        0 when xpass count is 0; 1 when xpasses remain; 2 on usage/IO error.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--from-log",
        metavar="PATH",
        required=True,
        help="Pytest terminal log to parse ('-' = stdin).",
    )
    args = parser.parse_args(argv)

    try:
        if args.from_log == "-":
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
