#!/usr/bin/env python3
"""Guard: application code must use loguru, not stdlib logging.

Fails when ``src/mergecraft/**/*.py`` outside the logging bridge imports stdlib
``logging``. Stdlib logging is allowed only under ``src/mergecraft/logging/``.

Module: scripts.check_loguru_only
Depends: pathlib, re, sys

Exports:
    main — CLI entry; scans for forbidden stdlib ``logging`` imports.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MERGECRAFT_SRC = REPO / "src" / "mergecraft"

_IMPORT_LOGGING = re.compile(r"^\s*(import\s+logging|from\s+logging\b)", re.MULTILINE)
_GRANDFATHER_LOGGING: frozenset[str] = frozenset()


def _rel(path: Path) -> str:
    """Return repo-relative posix path for ``path``."""
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _is_allowed(path: Path) -> bool:
    """Return True when stdlib logging is permitted for ``path``."""
    rel = _rel(path)
    if rel in _GRANDFATHER_LOGGING:
        return True
    parts = Path(rel).parts
    return (
        len(parts) >= 3 and parts[0] == "src" and parts[1] == "mergecraft" and parts[2] == "logging"
    )


def main() -> int:
    """Scan mergecraft sources for forbidden stdlib logging imports."""
    if not MERGECRAFT_SRC.is_dir():
        print(f"missing source tree: {MERGECRAFT_SRC}", file=sys.stderr)
        return 1

    violations: list[str] = []
    for path in sorted(MERGECRAFT_SRC.rglob("*.py")):
        if _is_allowed(path):
            continue
        text = path.read_text(encoding="utf-8")
        if _IMPORT_LOGGING.search(text):
            violations.append(_rel(path))

    if violations:
        print(
            "stdlib logging imports are forbidden outside src/mergecraft/logging/:", file=sys.stderr
        )
        for rel in violations:
            print(f"  {rel}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
