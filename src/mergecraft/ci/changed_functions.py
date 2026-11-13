"""Resolve a diff hunk to its enclosing function (C-D4).

An unattributable hunk — no enclosing symbol, missing source, or an
unsupported language — yields nothing. There is no file-scope fallback.

Module: mergecraft.ci.changed_functions
Depends: mergecraft.analyzers.scope

Exports:
    Classes:
        ChangedFunction — One enclosing symbol (name, qualname, path, start_line).
    Functions:
        resolve_enclosing_symbol — Innermost function covering ``line``.
        changed_functions_from_diff — Unique enclosing symbols for hunk lines.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

from mergecraft.analyzers.scope import parse_diff_scope


@dataclass(frozen=True, slots=True)
class ChangedFunction:
    """One function that encloses at least one changed line.

    ``qualname`` is the dotted path of enclosing classes and functions
    (``Foo.bar``, ``outer.inner``), the key coverage.py and its lcov writer
    use for methods and nested functions. Empty means "same as ``name``".
    """

    name: str
    path: str
    start_line: int
    qualname: str = ""

    @property
    def qualified_name(self) -> str:
        """``qualname`` when known, else the bare ``name``."""
        return self.qualname or self.name


_FunctionNode = ast.FunctionDef | ast.AsyncFunctionDef


def _iter_functions(tree: ast.AST) -> list[tuple[_FunctionNode, str]]:
    """Every function in ``tree`` with its dotted qualified name."""
    found: list[tuple[_FunctionNode, str]] = []
    stack: list[tuple[ast.AST, tuple[str, ...]]] = [(tree, ())]
    while stack:
        node, prefix = stack.pop()
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qualified = (*prefix, child.name)
                found.append((child, ".".join(qualified)))
                stack.append((child, qualified))
            elif isinstance(child, ast.ClassDef):
                stack.append((child, (*prefix, child.name)))
            else:
                stack.append((child, prefix))
    return found


def resolve_enclosing_symbol(path: str, line: int, source: str) -> ChangedFunction | None:
    """Return the innermost function whose span covers ``line``, or ``None``.

    Args:
        path: Repo-relative path recorded on the symbol.
        line: 1-indexed line in ``source``.
        source: File contents used to parse the AST.

    Returns:
        The enclosing ``ChangedFunction``, or ``None`` when the line sits
        outside every function (module-level code, parse failure).
    """
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None

    return _resolve_from_functions(path, line, _iter_functions(tree))


def _resolve_from_functions(
    path: str, line: int, functions: list[tuple[_FunctionNode, str]]
) -> ChangedFunction | None:
    best: ChangedFunction | None = None
    best_span = -1
    for node, qualname in functions:
        start = int(node.lineno)
        end = int(getattr(node, "end_lineno", None) or start)
        if start <= line <= end:
            span = end - start
            # Innermost: the covering function with the smallest span. Nested
            # functions beat their enclosing def when both cover ``line``.
            if best is None or span < best_span or (span == best_span and start > best.start_line):
                best = ChangedFunction(
                    name=node.name, path=path, start_line=start, qualname=qualname
                )
                best_span = span
    return best


def changed_functions_from_diff(
    diff: str,
    source_tree: Mapping[str, str],
) -> list[ChangedFunction]:
    """Return unique enclosing functions for every new-side hunk line.

    Args:
        diff: Unified diff.
        source_tree: Path → current file text. Missing paths are skipped
            (unresolvable, never file-scoped).

    Returns:
        Deduplicated enclosing symbols in first-seen order.
    """
    if not diff.strip():
        return []

    seen: set[tuple[str, str, int]] = set()
    ordered: list[ChangedFunction] = []
    scope = parse_diff_scope(diff)
    for path, ranges in scope.hunk_ranges.items():
        source = source_tree.get(path)
        if source is None:
            continue
        try:
            functions = _iter_functions(ast.parse(source))
        except (SyntaxError, ValueError):
            continue
        for start, end in ranges:
            for line in range(start, end + 1):
                symbol = _resolve_from_functions(path, line, functions)
                if symbol is None:
                    continue
                key = (symbol.path, symbol.name, symbol.start_line)
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(symbol)
    return ordered


#: Skip reason when every changed file is in a language with no resolver.
SKIP_CHANGED_LANGUAGE_UNSUPPORTED = "changed_function_language_unsupported"
# Enclosing-symbol resolution parses Python only (``ast``).
_RESOLVABLE_SUFFIXES = (".py", ".pyi")


def unsupported_language_skip(diff: str) -> str | None:
    """Return a named skip when no changed file is in a resolvable language.

    Coverage (lcov, Cobertura) and mutation (Stryker) reports for JS/TS, Java,
    Go and other languages parse, but nothing here can map their changed hunks
    to a function. Callers report this reason instead of an empty result.
    """
    if not diff.strip():
        return None
    paths = list(parse_diff_scope(diff).hunk_ranges)
    if paths and not any(path.endswith(_RESOLVABLE_SUFFIXES) for path in paths):
        return SKIP_CHANGED_LANGUAGE_UNSUPPORTED
    return None


__all__ = [
    "SKIP_CHANGED_LANGUAGE_UNSUPPORTED",
    "ChangedFunction",
    "changed_functions_from_diff",
    "resolve_enclosing_symbol",
    "unsupported_language_skip",
]
