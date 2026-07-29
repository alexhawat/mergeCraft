"""Planted pattern-scanner taint sink (catalog C3)."""

from __future__ import annotations

import sys


def run_user_code(user_input: str) -> None:
    # Planted: semgrep/ast-grep taint-style sink — verify before review (D11)
    eval(user_input)  # noqa: S307


def main() -> None:
    run_user_code(sys.argv[1] if len(sys.argv) > 1 else "")
