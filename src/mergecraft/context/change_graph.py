"""Change graph — changed symbol → dependents, tests, and contracts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal

from mergecraft.context.call_graph import CallGraph, build_call_graph

_CONTRACT_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".proto"})
_TEST_DIR_NAMES = frozenset({"tests", "test"})


@dataclass(frozen=True, slots=True)
class ChangedSymbol:
    """One diff-touched symbol in a repository."""

    path: str
    name: str
    kind: str


@dataclass(frozen=True, slots=True)
class ChangeGraphResult:
    """Dependents, covering tests, and affected contracts for changed symbols."""

    dependents: tuple[str, ...]
    tests: tuple[str, ...]
    contracts: tuple[str, ...]


def resolve_change_graph(
    *,
    repo_root: Path,
    tree_sha: str,
    changed: list[ChangedSymbol],
) -> ChangeGraphResult:
    """Resolve dependents, tests, and contracts affected by ``changed`` symbols."""
    graph = build_call_graph(repo_root=repo_root, tree_sha=tree_sha)
    dependents: set[str] = set()
    tests: set[str] = set()
    contracts: set[str] = set()

    for symbol in changed:
        qualified = _qualify_symbol(symbol)
        dependents.update(_dependents_for(graph, qualified, symbol.name))
        tests.update(_covering_tests(repo_root, symbol))
        contracts.update(
            _affected_contracts(
                repo_root,
                symbol_names={symbol.name, *_symbol_tail(qualified), *dependents},
            )
        )

    return ChangeGraphResult(
        dependents=tuple(sorted(dependents)),
        tests=tuple(sorted(tests)),
        contracts=tuple(sorted(contracts)),
    )


def _qualify_symbol(symbol: ChangedSymbol) -> str:
    module = _module_name(symbol.path)
    return f"{module}.{symbol.name}" if module else symbol.name


def _module_name(rel_path: str) -> str:
    stem = rel_path.removesuffix(".py")
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    if stem.startswith("src/"):
        stem = stem.removeprefix("src/")
    return stem.replace("/", ".")


def _symbol_tail(qualified: str) -> set[str]:
    return {qualified.split(".")[-1]}


def _dependents_for(graph: CallGraph, qualified: str, bare_name: str) -> set[str]:
    targets = {qualified, bare_name}
    found: set[str] = set()
    for edge in graph.edges:
        if edge.callee in targets or edge.callee.endswith(f".{bare_name}"):
            found.add(edge.caller)
    return found


def _covering_tests(repo_root: Path, symbol: ChangedSymbol) -> set[str]:
    tests: set[str] = set()
    module = _module_name(symbol.path)
    needles = (
        f"from {module} import {symbol.name}",
        f"import {module}",
        symbol.name,
    )
    for rel_path in _iter_test_files(repo_root):
        source = (repo_root / rel_path).read_text(encoding="utf-8")
        if any(needle in source for needle in needles):
            tests.add(rel_path)
    return tests


def _iter_test_files(repo_root: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(repo_root.rglob("test*.py")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith(".git/"):
            continue
        parts = rel.split("/")
        if any(part in _TEST_DIR_NAMES for part in parts):
            paths.append(rel)
    return paths


def _affected_contracts(repo_root: Path, *, symbol_names: set[str]) -> set[str]:
    contracts: set[str] = set()
    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith(".git/"):
            continue
        if path.suffix.casefold() not in _CONTRACT_SUFFIXES and "contracts" not in rel:
            continue
        if path.suffix.casefold() not in _CONTRACT_SUFFIXES:
            continue
        source = path.read_text(encoding="utf-8")
        if any(re.search(rf"\b{re.escape(name)}\b", source) for name in symbol_names if name):
            contracts.add(rel)
    return contracts


__all__ = ["ChangeGraphResult", "ChangedSymbol", "resolve_change_graph"]
