"""On-demand context expansion within a per-run token budget (CC3)."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import TYPE_CHECKING

from mergecraft.context.provenance import ContextItem

if TYPE_CHECKING:
    from mergecraft.utils.run_bounds import BudgetTracker

_DEFAULT_REPO = "local"
_DEFAULT_SHA = "working-tree"


@dataclass(frozen=True, slots=True)
class ExpansionResult:
    """Dynamic expansion output with token accounting."""

    items: tuple[ContextItem, ...]
    truncated: bool
    token_cost: int


def expand_enclosing_scope(
    *,
    repo_root: Path,
    path: str,
    symbol: str,
) -> ExpansionResult:
    """Retrieve the enclosing scope for ``symbol`` in ``path`` on demand."""
    text = _extract_scope(repo_root / path, symbol=symbol)
    item = _context_item(path=path, text=text, reason="dynamic_expansion")
    token_cost = item.token_cost
    return ExpansionResult(items=(item,), truncated=False, token_cost=token_cost)


def expand_with_budget(
    *,
    repo_root: Path,
    path: str,
    symbol: str,
    token_budget: int,
    budget_tracker: BudgetTracker | None = None,
) -> ExpansionResult:
    """Expand ``symbol`` without exceeding ``token_budget``."""
    source = (repo_root / path).read_text(encoding="utf-8")
    chunks = _scope_chunks(source, symbol=symbol)
    items: list[ContextItem] = []
    total_tokens = 0
    truncated = False

    for chunk in chunks:
        cost = _estimate_tokens(chunk)
        if total_tokens + cost > token_budget:
            truncated = True
            remaining = max(0, token_budget - total_tokens)
            if remaining > 0:
                clipped = chunk[: remaining * 4]
                item = _context_item(path=path, text=clipped, reason="dynamic_expansion")
                items.append(item)
                total_tokens += item.token_cost
                if budget_tracker is not None:
                    budget_tracker.record_tokens(item.token_cost)
            break
        item = _context_item(path=path, text=chunk, reason="dynamic_expansion")
        items.append(item)
        total_tokens += item.token_cost
        if budget_tracker is not None:
            budget_tracker.record_tokens(item.token_cost)

    return ExpansionResult(
        items=tuple(items),
        truncated=truncated,
        token_cost=total_tokens,
    )


def _context_item(*, path: str, text: str, reason: str) -> ContextItem:
    return ContextItem(
        repo=_DEFAULT_REPO,
        sha=_DEFAULT_SHA,
        path=path,
        reason=reason,
        text=text,
        token_cost=_estimate_tokens(text),
    )


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _extract_scope(path: Path, *, symbol: str) -> str:
    source = path.read_text(encoding="utf-8")
    if "." in symbol:
        class_name, member_name = symbol.split(".", 1)
        class_source = _class_source(source, class_name=class_name)
        member_source = _member_source(class_source or source, member_name=member_name)
        parts = [part for part in (class_source, member_source) if part]
        return "\n\n".join(parts)
    return _member_source(source, member_name=symbol) or source


def _scope_chunks(source: str, *, symbol: str) -> list[str]:
    if "." in symbol:
        class_name, _member_name = symbol.split(".", 1)
        class_source = _class_source(source, class_name=class_name)
        if class_source is None:
            return [source]
        lines = class_source.splitlines(keepends=True)
        return ["".join(lines[: index + 1]) for index in range(len(lines))]

    class_source = _class_source(source, class_name=symbol)
    if class_source is None:
        member_source = _member_source(source, member_name=symbol)
        return [member_source or source]

    lines = class_source.splitlines(keepends=True)
    return ["".join(lines[: index + 1]) for index in range(len(lines))]


def _class_source(source: str, *, class_name: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = source.splitlines(keepends=True)
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            return "".join(lines[start:end])
    return None


def _member_source(source: str, *, member_name: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None
    lines = source.splitlines(keepends=True)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == member_name:
            start = node.lineno - 1
            end = node.end_lineno or node.lineno
            return "".join(lines[start:end])
    return None


__all__ = ["ExpansionResult", "expand_enclosing_scope", "expand_with_budget"]
