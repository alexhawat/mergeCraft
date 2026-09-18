"""Resolve a diff hunk to its enclosing function (C-D4).

An unattributable hunk — no enclosing symbol, missing source, or an
unsupported language — yields nothing. There is no file-scope fallback.

Module: mergecraft.ci.changed_functions
Depends: mergecraft.analyzers.scope

Exports:
    Classes:
        ChangedFunction — One enclosing symbol (name, path, start_line).
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
    """One function that encloses at least one changed line."""

    name: str
    path: str
    start_line: int


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

    best: ChangedFunction | None = None
    best_span = -1
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        start = int(node.lineno)
        end = int(getattr(node, "end_lineno", None) or start)
        if start <= line <= end:
            span = end - start
            # Innermost: the covering function with the smallest span. Nested
            # functions beat their enclosing def when both cover ``line``.
            if best is None or span < best_span or (span == best_span and start > best.start_line):
                best = ChangedFunction(name=node.name, path=path, start_line=start)
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
        for start, end in ranges:
            for line in range(start, end + 1):
                symbol = resolve_enclosing_symbol(path, line, source)
                if symbol is None:
                    continue
                key = (symbol.path, symbol.name, symbol.start_line)
                if key in seen:
                    continue
                seen.add(key)
                ordered.append(symbol)
    return ordered


__all__ = [
    "ChangedFunction",
    "changed_functions_from_diff",
    "resolve_enclosing_symbol",
]
