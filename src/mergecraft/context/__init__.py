"""Repository context engine — repo map, symbol index, provenance, instruction discovery."""

from mergecraft.context.call_graph import CallGraph, build_call_graph
from mergecraft.context.change_graph import ChangedSymbol, ChangeGraphResult, resolve_change_graph
from mergecraft.context.dynamic_expansion import (
    ExpansionResult,
    expand_enclosing_scope,
    expand_with_budget,
)
from mergecraft.context.git_history import TargetedBlameResult, targeted_blame
from mergecraft.context.instruction_discovery import render_review_context
from mergecraft.context.provenance import ContextItem, inspect_context
from mergecraft.context.repo_map import RepoMap, build_repo_map
from mergecraft.context.symbol_index import SymbolIndexResult, index_symbols

__all__ = [
    "CallGraph",
    "ChangeGraphResult",
    "ChangedSymbol",
    "ContextItem",
    "ExpansionResult",
    "RepoMap",
    "SymbolIndexResult",
    "TargetedBlameResult",
    "build_call_graph",
    "build_repo_map",
    "expand_enclosing_scope",
    "expand_with_budget",
    "index_symbols",
    "inspect_context",
    "render_review_context",
    "resolve_change_graph",
    "targeted_blame",
]
