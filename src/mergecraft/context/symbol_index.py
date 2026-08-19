"""Symbol indexing with tree-sitter and a generic regex fallback (D6)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol, cast

from mergecraft.utils.bounded_text import read_bounded_text

Backend = Literal["tree_sitter", "generic"]
Fidelity = Literal["full", "reduced"]

_TREE_SITTER_SUFFIXES = frozenset({".py"})
_GENERIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"^\s*(?:async\s+)?def\s+(\w+)\s*\(", re.MULTILINE),
    re.compile(r"^\s*class\s+(\w+)\s*[:(]", re.MULTILINE),
    re.compile(r"^\s*function\s+(\w+)\s*\(", re.MULTILINE),
)


class _CacheProto(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class Symbol:
    """One indexed symbol name from a source file."""

    name: str
    kind: str = "symbol"


@dataclass(frozen=True, slots=True)
class SymbolIndexResult:
    """Indexed symbols for one blob with backend and fidelity metadata."""

    symbols: tuple[Symbol, ...]
    backend: Backend
    fidelity: Fidelity
    fidelity_note: str | None = None


def index_symbols(
    *,
    repo_root: Path,
    rel_path: str,
    blob_sha: str,
    cache: _CacheProto | None = None,
    source: str | None = None,
) -> SymbolIndexResult:
    """Index symbols for ``rel_path`` at ``blob_sha``."""
    if cache is not None:
        cached = cache.get(blob_sha)
        if cached is not None:
            return cast("SymbolIndexResult", cached)

    if source is None:
        source = read_bounded_text(repo_root / rel_path)
        if source is None:
            result = SymbolIndexResult(
                symbols=(),
                backend="generic",
                fidelity="reduced",
                fidelity_note="source file unreadable, symlink, or exceeds size bound",
            )
            if cache is not None:
                cache.set(blob_sha, result)
            return result
    suffix = Path(rel_path).suffix.casefold()
    if suffix in _TREE_SITTER_SUFFIXES:
        result = _index_with_tree_sitter(source)
    else:
        result = _index_with_generic(source)

    if cache is not None:
        cache.set(blob_sha, result)
    return result


def _index_with_tree_sitter(source: str) -> SymbolIndexResult:
    import tree_sitter_python as tspython
    from tree_sitter import Language, Node, Parser

    parser = Parser(Language(tspython.language()))
    tree = parser.parse(source.encode("utf-8"))
    symbols: list[Symbol] = []

    def walk(node: Node) -> None:
        if node.type == "class_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = source[name_node.start_byte : name_node.end_byte]
                symbols.append(Symbol(name=name, kind="class"))
        elif node.type == "function_definition":
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = source[name_node.start_byte : name_node.end_byte]
                symbols.append(Symbol(name=name, kind="function"))
        for child in node.children:
            walk(child)

    walk(tree.root_node)
    return SymbolIndexResult(
        symbols=tuple(symbols),
        backend="tree_sitter",
        fidelity="full",
    )


def _index_with_generic(source: str) -> SymbolIndexResult:
    seen: set[str] = set()
    symbols: list[Symbol] = []
    for pattern in _GENERIC_PATTERNS:
        for match in pattern.finditer(source):
            name = match.group(1)
            if name not in seen:
                seen.add(name)
                kind = "function" if "function" in pattern.pattern else "symbol"
                symbols.append(Symbol(name=name, kind=kind))
    return SymbolIndexResult(
        symbols=tuple(symbols),
        backend="generic",
        fidelity="reduced",
        fidelity_note="generic regex fallback; no tree-sitter grammar for this language",
    )


__all__ = ["Symbol", "SymbolIndexResult", "index_symbols"]
