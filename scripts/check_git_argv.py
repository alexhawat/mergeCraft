#!/usr/bin/env python3
"""Guard: bare ``["git", …]`` list literals must not appear outside git_hardening.

Root-side git must route through :func:`mergecraft.utils.git_hardening.git_argv`
so hostile ``.git/config`` cannot execute. This checker fails ``make lint`` when
any ``src/mergecraft/**/*.py`` file outside ``utils/git_hardening.py`` embeds a
list literal whose first element is the string ``git``.

Module: scripts.check_git_argv
Depends: ast, pathlib, sys

Exports:
    main — CLI entry; scans for forbidden bare git list literals.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MERGECRAFT_SRC = REPO / "src" / "mergecraft"
_ALLOWED_REL = "src/mergecraft/utils/git_hardening.py"


def _rel(path: Path) -> str:
    try:
        return path.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return path.as_posix()


def _is_git_list_literal(node: ast.AST) -> bool:
    if not isinstance(node, ast.List):
        return False
    if not node.elts:
        return False
    first = node.elts[0]
    return isinstance(first, ast.Constant) and first.value == "git"


class _Visitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: list[int] = []

    def visit_List(self, node: ast.List) -> None:
        if _is_git_list_literal(node):
            self.violations.append(node.lineno)
        self.generic_visit(node)


def _scan_file(path: Path) -> list[int]:
    rel = _rel(path)
    if rel == _ALLOWED_REL:
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except OSError:
        return []
    tree = ast.parse(source, filename=rel)
    visitor = _Visitor()
    visitor.visit(tree)
    return visitor.violations


def main() -> int:
    """Scan mergecraft sources (or explicit paths) for bare git list literals."""
    if len(sys.argv) > 1:
        targets = [Path(arg) for arg in sys.argv[1:]]
    else:
        if not MERGECRAFT_SRC.is_dir():
            print(f"missing source tree: {MERGECRAFT_SRC}", file=sys.stderr)
            return 1
        targets = sorted(MERGECRAFT_SRC.rglob("*.py"))

    violations: list[str] = []
    for path in targets:
        for lineno in _scan_file(path):
            violations.append(f"{_rel(path)}:{lineno}: bare ['git', …] list literal")

    if violations:
        print(
            "route git subprocess argv through mergecraft.utils.git_hardening.git_argv:",
            file=sys.stderr,
        )
        for item in violations:
            print(f"  {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
