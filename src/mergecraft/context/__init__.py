"""Repository context engine — repo map, symbol index, provenance, instruction discovery."""

from mergecraft.context.instruction_discovery import render_review_context
from mergecraft.context.provenance import ContextItem, inspect_context
from mergecraft.context.repo_map import RepoMap, build_repo_map
from mergecraft.context.symbol_index import SymbolIndexResult, index_symbols

__all__ = [
    "ContextItem",
    "RepoMap",
    "SymbolIndexResult",
    "build_repo_map",
    "index_symbols",
    "inspect_context",
    "render_review_context",
]
