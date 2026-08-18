"""Change graph — changed symbol → dependents, tests, and contracts."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import TYPE_CHECKING

from mergecraft.context.call_graph import CallGraph, build_call_graph
from mergecraft.context.repo_paths import iter_repo_files

if TYPE_CHECKING:
    from mergecraft.utils.run_bounds import RunBounds

_CONTRACT_SUFFIXES = frozenset({".yaml", ".yml", ".json", ".proto"})
_TEST_DIR_NAMES = frozenset({"tests", "test"})
_FROM_IMPORT = re.compile(r"from\s+{module}\s+import\s+.*\b{symbol}\b")
_IMPORT_MODULE = re.compile(r"\bimport\s+{module}\b")


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
    run_bounds: RunBounds | None = None,
) -> ChangeGraphResult:
    """Resolve dependents, tests, and contracts affected by ``changed`` symbols."""
    graph = build_call_graph(repo_root=repo_root, tree_sha=tree_sha)
    deadline = _context_deadline(run_bounds)
    dependents: set[str] = set()
    tests: set[str] = set()
    contracts: set[str] = set()

    for symbol in changed:
        if _timed_out(deadline):
            break
        qualified = _qualify_symbol(symbol)
        dependents.update(_dependents_for(graph, qualified, symbol.name))
        tests.update(_covering_tests(repo_root, symbol, deadline=deadline))
        contracts.update(
            _affected_contracts(
                repo_root,
                symbol_names={symbol.name, *_symbol_tail(qualified), *dependents},
                deadline=deadline,
            )
        )

    return ChangeGraphResult(
        dependents=tuple(sorted(dependents)),
        tests=tuple(sorted(tests)),
        contracts=tuple(sorted(contracts)),
    )


def _context_deadline(run_bounds: RunBounds | None) -> float | None:
    if run_bounds is None:
        return None
    return time.monotonic() + run_bounds.context_retrieval_timeout_s


def _timed_out(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() > deadline


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


def _covering_tests(
    repo_root: Path,
    symbol: ChangedSymbol,
    *,
    deadline: float | None,
) -> set[str]:
    tests: set[str] = set()
    module = _module_name(symbol.path)
    from_import = _FROM_IMPORT.pattern.format(
        module=re.escape(module),
        symbol=re.escape(symbol.name),
    )
    import_module = _IMPORT_MODULE.pattern.format(module=re.escape(module))
    for rel_path in _iter_test_files(repo_root, deadline=deadline):
        source = (repo_root / rel_path).read_text(encoding="utf-8")
        if re.search(from_import, source) or re.search(import_module, source):
            tests.add(rel_path)
    return tests


def _iter_test_files(repo_root: Path, *, deadline: float | None) -> list[str]:
    paths: list[str] = []

    def _is_test_file(path: Path) -> bool:
        if not path.name.startswith("test") or path.suffix != ".py":
            return False
        rel = path.relative_to(repo_root).as_posix()
        return any(part in _TEST_DIR_NAMES for part in rel.split("/"))

    for rel in iter_repo_files(repo_root, predicate=_is_test_file, deadline=deadline):
        paths.append(rel)
    return paths


def _affected_contracts(
    repo_root: Path,
    *,
    symbol_names: set[str],
    deadline: float | None,
) -> set[str]:
    contracts: set[str] = set()

    def _is_contract(path: Path) -> bool:
        rel = path.relative_to(repo_root).as_posix()
        if path.suffix.casefold() not in _CONTRACT_SUFFIXES:
            return False
        return "contracts" in rel or path.suffix.casefold() in _CONTRACT_SUFFIXES

    for rel in iter_repo_files(repo_root, predicate=_is_contract, deadline=deadline):
        source = (repo_root / rel).read_text(encoding="utf-8")
        if any(re.search(rf"\b{re.escape(name)}\b", source) for name in symbol_names if name):
            contracts.add(rel)
    return contracts


__all__ = ["ChangeGraphResult", "ChangedSymbol", "resolve_change_graph"]
