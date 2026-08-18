"""Call graph over the DG3 symbol index — imports, references, and callers."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import Any, Literal, Protocol, cast

from mergecraft.context.repo_paths import git_blob_sha, git_ls_tree_paths, git_show_text
from mergecraft.context.symbol_index import index_symbols

EdgeKind = Literal["import", "reference", "call"]

_PYTHON_SUFFIX = ".py"


class _CacheProto(Protocol):
    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...


@dataclass(frozen=True, slots=True)
class CallEdge:
    """One directed relationship between caller and callee symbols or modules."""

    kind: EdgeKind
    caller: str
    callee: str


@dataclass(frozen=True, slots=True)
class CallGraph:
    """Indexed import, reference, and call edges for one repository tree."""

    edges: tuple[CallEdge, ...]


def build_call_graph(
    *,
    repo_root: Path,
    tree_sha: str,
    cache: _CacheProto | None = None,
) -> CallGraph:
    """Index import, reference, and call edges for ``tree_sha``."""
    if cache is not None:
        cached = cache.get(tree_sha)
        if cached is not None:
            return cast("CallGraph", cached)

    edges: list[CallEdge] = []
    for rel_path in git_ls_tree_paths(repo_root, tree_sha, suffix=_PYTHON_SUFFIX):
        module = _module_name(rel_path)
        blob_sha = git_blob_sha(repo_root, tree_sha, rel_path)
        source = git_show_text(repo_root, tree_sha, rel_path)
        if source is None:
            continue
        index_symbols(
            repo_root=repo_root,
            rel_path=rel_path,
            blob_sha=blob_sha,
            source=source,
        )
        edges.extend(_edges_for_file(module=module, rel_path=rel_path, source=source))

    graph = CallGraph(edges=tuple(edges))
    if cache is not None:
        cache.set(tree_sha, graph)
    return graph


def _module_name(rel_path: str) -> str:
    stem = rel_path.removesuffix(_PYTHON_SUFFIX)
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    if stem.startswith("src/"):
        stem = stem.removeprefix("src/")
    return stem.replace("/", ".")


def _edges_for_file(*, module: str, rel_path: str, source: str) -> list[CallEdge]:
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return []

    imports: dict[str, str] = {}
    edges: list[CallEdge] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None:
                continue
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = f"{node.module}.{alias.name}"
                edges.append(
                    CallEdge(
                        kind="import",
                        caller=module,
                        callee=f"{node.module}.{alias.name}",
                    )
                )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name
                imports[local] = alias.name
                edges.append(
                    CallEdge(
                        kind="import",
                        caller=module,
                        callee=alias.name,
                    )
                )

    collector = _CallEdgeCollector(module=module, imports=imports)
    collector.visit(tree)
    edges.extend(collector.edges)
    return edges


class _CallEdgeCollector(ast.NodeVisitor):
    """Collect call/reference edges with module-, class-, and function-qualified callers."""

    def __init__(self, *, module: str, imports: dict[str, str]) -> None:
        self._module = module
        self._imports = imports
        self._class_stack: list[str] = []
        self._func_stack: list[str] = []
        self.edges: list[CallEdge] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._class_stack.append(node.name)
        self.generic_visit(node)
        self._class_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._func_stack.append(node.name)
        self.generic_visit(node)
        self._func_stack.pop()

    def visit_Call(self, node: ast.Call) -> None:
        caller = self._caller_name()
        callee = _callee_name(node.func, imports=self._imports, module=self._module)
        if callee:
            self.edges.append(CallEdge(kind="call", caller=caller, callee=callee))
            self.edges.append(CallEdge(kind="reference", caller=caller, callee=callee))

    def _caller_name(self) -> str:
        if self._func_stack:
            parts = [self._module, *self._class_stack, self._func_stack[-1]]
            return ".".join(parts)
        if self._class_stack:
            return f"{self._module}.{self._class_stack[-1]}"
        return self._module


def _callee_name(
    node: ast.expr,
    *,
    imports: dict[str, str],
    module: str,
) -> str | None:
    del module
    if isinstance(node, ast.Name):
        if node.id in imports:
            return imports[node.id]
        return node.id
    if isinstance(node, ast.Attribute):
        parts: list[str] = []
        current: ast.expr = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            base = imports.get(current.id, current.id)
            parts.reverse()
            return ".".join([base, *parts])
    return None


__all__ = ["CallEdge", "CallGraph", "EdgeKind", "build_call_graph"]
