#!/usr/bin/env python3
"""Guard: CLI modules must not construct bare stdout Rich consoles (D14).

Fails when ``src/mergecraft/cli/**/*.py`` outside the canonical
``consoles.py`` module calls ``Console(...)`` without ``stderr=True``.

Module: scripts.check_cli_consoles
Depends: ast, pathlib, sys

Exports:
    find_cli_console_violations — AST scan for disallowed console sites
    main — CLI entry; exits non-zero when violations remain
"""

from __future__ import annotations

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CLI_ROOT = REPO / "src" / "mergecraft" / "cli"
CANONICAL_MODULE = CLI_ROOT / "consoles.py"


@dataclass(frozen=True, slots=True)
class ConsoleViolation:
    """A ``Console(...)`` site under ``src/mergecraft/cli/`` missing ``stderr=True``."""

    path: str
    line: int
    col: int
    snippet: str


def _console_call_has_stderr_true(node: ast.Call) -> bool:
    for keyword in node.keywords:
        if keyword.arg == "stderr":
            value = keyword.value
            if isinstance(value, ast.Constant) and value.value is True:
                return True
    return False


def _is_console_call(node: ast.AST) -> bool:
    if not isinstance(node, ast.Call):
        return False
    func = node.func
    return isinstance(func, ast.Name) and func.id == "Console"


def find_cli_console_violations(root: Path = CLI_ROOT) -> list[ConsoleViolation]:
    """Return ``Console(...)`` sites under ``cli/`` that omit ``stderr=True``."""
    display_base = REPO if root == CLI_ROOT else root
    violations: list[ConsoleViolation] = []
    for path in sorted(root.rglob("*.py")):
        if root == CLI_ROOT and path.resolve() == CANONICAL_MODULE.resolve():
            continue
        rel = path.relative_to(display_base).as_posix()
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel)
        for node in ast.walk(tree):
            if not _is_console_call(node):
                continue
            if _console_call_has_stderr_true(node):
                continue
            snippet = ast.get_source_segment(source, node) or "Console(...)"
            violations.append(
                ConsoleViolation(
                    path=rel,
                    line=node.lineno,
                    col=node.col_offset + 1,
                    snippet=snippet.splitlines()[0].strip(),
                )
            )
    return violations


def main() -> int:
    """Scan ``src/mergecraft/cli/`` and fail when stdout consoles remain."""
    violations = find_cli_console_violations()
    if not violations:
        return 0
    for item in violations:
        print(f"{item.path}:{item.line}:{item.col} {item.snippet}", file=sys.stderr)
    print(
        f"check_cli_consoles: {len(violations)} bare Console() site(s) under src/mergecraft/cli/",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
