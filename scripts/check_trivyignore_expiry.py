#!/usr/bin/env python3
"""Validate ``.trivyignore`` waiver entries (D7 / release-gating W3).

Every ignored CVE must have ``justification:`` and ``expiry: YYYY-MM-DD`` in its
own preceding comment block (after the previous CVE, not a sliding character
window). Entries past their expiry date fail the check so waivers cannot silently
rot.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import UTC, date, datetime
from pathlib import Path

_CVE = re.compile(r"^CVE-\d{4}-\d+\b", re.MULTILINE)
_EXPIRY = re.compile(r"expir(?:y|es|ation)\s*[:=]\s*(\d{4}-\d{2}-\d{2})", re.IGNORECASE)
_JUSTIFICATION = re.compile(r"justification\s*[:=]\s*\S+", re.IGNORECASE)


def _parse_expiry(window: str) -> date | None:
    match = _EXPIRY.search(window)
    if match is None:
        return None
    return datetime.strptime(match.group(1), "%Y-%m-%d").replace(tzinfo=UTC).date()


def check_trivyignore(path: Path) -> int:
    """Return 0 when all CVE entries are valid and unexpired; 1 on violations."""
    if not path.is_file():
        print(f".trivyignore missing: {path}", file=sys.stderr)
        return 1

    text = path.read_text(encoding="utf-8")
    today = datetime.now(tz=UTC).date()
    failures: list[str] = []

    prev_end = 0
    for match in _CVE.finditer(text):
        cve = match.group(0)
        # Metadata is scoped to this entry: after the previous CVE through this
        # line. A lookbehind/lookahead character window would let a bare CVE
        # inherit a neighbor's justification/expiry.
        window = text[prev_end : match.end()]
        prev_end = match.end()

        if not _JUSTIFICATION.search(window):
            failures.append(f"{cve}: missing justification")
            continue

        expiry = _parse_expiry(window)
        if expiry is None:
            failures.append(f"{cve}: missing expiry date (YYYY-MM-DD)")
            continue
        if expiry < today:
            failures.append(f"{cve}: expired on {expiry.isoformat()}")

    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(".trivyignore"),
        help="Path to .trivyignore (default: ./.trivyignore)",
    )
    args = parser.parse_args(argv)
    return check_trivyignore(args.path)


if __name__ == "__main__":
    raise SystemExit(main())
