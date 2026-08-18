"""Call graph over the DG3 symbol index — imports, references, and callers."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import Any, Literal, Protocol, cast

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
    for rel_path in _iter_python_files(repo_root):
        module = _module_name(rel_path)
        blob_sha = _blob_sha(repo_root, rel_path)
        index_symbols(repo_root=repo_root, rel_path=rel_path, blob_sha=blob_sha)
        source = (repo_root / rel_path).read_text(encoding="utf-8")
        edges.extend(_edges_for_file(module=module, rel_path=rel_path, source=source))

    graph = CallGraph(edges=tuple(edges))
    if cache is not None:
        cache.set(tree_sha, graph)
    return graph


def _iter_python_files(repo_root: Path) -> list[str]:
    paths: list[str] = []
    for path in sorted(repo_root.rglob(f"*{_PYTHON_SUFFIX}")):
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if rel.startswith(".git/"):
            continue
        paths.append(rel)
    return paths


def _module_name(rel_path: str) -> str:
    stem = rel_path.removesuffix(_PYTHON_SUFFIX)
    if stem.endswith("/__init__"):
        stem = stem[: -len("/__init__")]
    if stem.startswith("src/"):
        stem = stem.removeprefix("src/")
    return stem.replace("/", ".")


def _blob_sha(repo_root: Path, rel_path: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "rev-parse", f"HEAD:{rel_path}"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        completed = None
    if completed is not None and completed.returncode == 0:
        return completed.stdout.strip()
    content = (repo_root / rel_path).read_bytes()
    return f"blob:{content.hex()[:40]}"


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

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            caller = f"{module}.{node.name}"
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    callee = _callee_name(child.func, imports=imports, module=module)
                    if callee:
                        edges.append(CallEdge(kind="call", caller=caller, callee=callee))
                        edges.append(CallEdge(kind="reference", caller=caller, callee=callee))

    return edges


def _callee_name(
    node: ast.expr,
    *,
    imports: dict[str, str],
    module: str,
) -> str | None:
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
