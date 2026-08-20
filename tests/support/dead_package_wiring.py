"""Import-graph helpers for dead-package wiring pins (sweep 20c W4 / #351-#353).

A *production call site* is a runtime import of ``mergecraft.{pr,requirements,xrepo}``
from ``src/mergecraft`` **outside** that package. Package-internal imports and
``TYPE_CHECKING``-only imports do not count (plan W0 / W4.1).
"""

from __future__ import annotations

import ast
from pathlib import Path

from tests.ci.workflow_support import REPO_ROOT

SRC_ROOT = REPO_ROOT / "src" / "mergecraft"
CLI_DIR = SRC_ROOT / "cli"

# Review / Action / CLI / MCP surfaces that count as product wiring when they
# import a dead package. Internal library modules in other packages also count
# (any non-self runtime import is a call site).
_DEAD_PACKAGES = frozenset({"pr", "requirements", "xrepo"})


def _is_type_checking_test(node: ast.expr) -> bool:
    if isinstance(node, ast.Name):
        return node.id == "TYPE_CHECKING"
    if isinstance(node, ast.Attribute):
        return node.attr == "TYPE_CHECKING"
    return False


def _imported_mergecraft_names(tree: ast.AST) -> set[str]:
    """Return dotted ``mergecraft.*`` module names imported at runtime."""
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking_test(node.test):
                for child in node.orelse:
                    self.visit(child)
                return
            self.generic_visit(node)

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                found.add(alias.name)
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.level == 0 and node.module:
                found.add(node.module)
                for alias in node.names:
                    found.add(f"{node.module}.{alias.name}")
            self.generic_visit(node)

    Visitor().visit(tree)
    return {name for name in found if name == "mergecraft" or name.startswith("mergecraft.")}


def _invoked_names(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            names.add(func.id)
        elif isinstance(func, ast.Attribute):
            names.add(func.attr)
    return names


def production_importers(package: str) -> list[str]:
    """Repo-relative ``src/mergecraft/...`` paths that runtime-import ``package``."""
    if package not in _DEAD_PACKAGES:
        msg = f"unknown dead package {package!r}"
        raise ValueError(msg)
    prefix = f"mergecraft.{package}"
    hits: list[str] = []
    for path in sorted(SRC_ROOT.rglob("*.py")):
        rel = path.relative_to(SRC_ROOT)
        if rel.parts[0] == package:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = _imported_mergecraft_names(tree)
        if any(name == prefix or name.startswith(f"{prefix}.") for name in imported):
            hits.append(rel.as_posix())
    return hits


def production_invoked_names(*, exclude_package: str | None = None) -> set[str]:
    """Function/attribute names invoked in production modules.

    ``exclude_package`` drops that package tree so a library calling itself
    cannot stand in for product wiring.
    """
    names: set[str] = set()
    for path in SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(SRC_ROOT)
        if exclude_package and rel.parts[0] == exclude_package:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names |= _invoked_names(tree)
    return names


def cli_cmd_path(*candidates: str) -> Path | None:
    """Return the first existing ``cli/<name>_cmd.py`` among ``candidates``."""
    for name in candidates:
        path = CLI_DIR / f"{name}_cmd.py"
        if path.is_file():
            return path
    return None


def root_callback_source() -> str:
    """Return ``cli/app.py`` text for D10 (no root-callback) assertions."""
    return (CLI_DIR / "app.py").read_text(encoding="utf-8")
