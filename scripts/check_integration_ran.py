#!/usr/bin/env python3
"""Fail when an integration pytest run executed zero tests (H2 / D9).

Parses the pytest summary line from a captured log (``make test-integration``
pipes stdout/stderr through ``tee``). Secret-gated skips must not satisfy the
meta-gate — at least one test must report passed or failed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_PASSED_THEN_FAILED = re.compile(
    r"(?P<passed>\d+) passed(?:, (?P<failed>\d+) failed)?",
)
_FAILED_THEN_PASSED = re.compile(
    r"(?P<failed>\d+) failed(?:, (?P<passed>\d+) passed)?",
)


def count_executed(log_text: str) -> int:
    """Return passed + failed from the last pytest summary line, or 0 when absent."""
    executed = 0
    for line in log_text.splitlines():
        candidates: list[int] = []
        passed_first = _PASSED_THEN_FAILED.search(line)
        if passed_first:
            candidates.append(
                int(passed_first.group("passed")) + int(passed_first.group("failed") or 0),
            )
        failed_first = _FAILED_THEN_PASSED.search(line)
        if failed_first:
            candidates.append(
                int(failed_first.group("failed")) + int(failed_first.group("passed") or 0),
            )
        if candidates:
            executed = max(candidates)
    return executed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--log",
        type=Path,
        required=True,
        help="Pytest stdout/stderr log to parse for the summary line",
    )
    args = parser.parse_args(argv)
    text = args.log.read_text(encoding="utf-8")
    executed = count_executed(text)
    if executed == 0:
        print(
            "Integration gate: zero tests executed (passed + failed == 0). "
            "Secret-gated skips must not satisfy the meta-gate.",
            file=sys.stderr,
        )
        return 1
    print(f"Integration gate: {executed} test(s) executed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
