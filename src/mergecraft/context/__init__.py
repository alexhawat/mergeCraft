"""Repository context engine — repo map, symbol index, provenance, instruction discovery."""

from mergecraft.context.call_graph import CallGraph, build_call_graph
from mergecraft.context.change_graph import ChangedSymbol, ChangeGraphResult, resolve_change_graph
from mergecraft.context.dynamic_expansion import (
    ExpansionResult,
    expand_enclosing_scope,
    expand_with_budget,
)
from mergecraft.context.external_files import ExternalContextFile, load_external_context_file
from mergecraft.context.git_history import TargetedBlameResult, targeted_blame
from mergecraft.context.instruction_discovery import (
    InstructionConflictResult,
    discover_instruction_paths,
    hash_injected_instructions,
    render_review_context,
    resolve_instruction_conflicts,
)
from mergecraft.context.operator import (
    LazyRetrieval,
    OmissionReport,
    RetrievalQualityReport,
    allocate_specialist_budgets,
    downgrade_for_omissions,
    evaluate_retrieval_quality,
    lazy_retrieve,
    report_omissions,
    score_relevance,
)
from mergecraft.context.provenance import ContextItem, inspect_context
from mergecraft.context.repo_map import RepoMap, build_repo_map
from mergecraft.context.symbol_index import SymbolIndexResult, index_symbols

__all__ = [
    "CallGraph",
    "ChangeGraphResult",
    "ChangedSymbol",
    "ContextItem",
    "ExpansionResult",
    "ExternalContextFile",
    "InstructionConflictResult",
    "LazyRetrieval",
    "OmissionReport",
    "RepoMap",
    "RetrievalQualityReport",
    "SymbolIndexResult",
    "TargetedBlameResult",
    "allocate_specialist_budgets",
    "build_call_graph",
    "build_repo_map",
    "discover_instruction_paths",
    "downgrade_for_omissions",
    "evaluate_retrieval_quality",
    "expand_enclosing_scope",
    "expand_with_budget",
    "hash_injected_instructions",
    "index_symbols",
    "inspect_context",
    "lazy_retrieve",
    "load_external_context_file",
    "render_review_context",
    "report_omissions",
    "resolve_change_graph",
    "resolve_instruction_conflicts",
    "score_relevance",
    "targeted_blame",
]
