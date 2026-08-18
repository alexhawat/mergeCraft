"""Contract surface indexing — OpenAPI, GraphQL, protobuf, and export symbols."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for contract traversal


@dataclass(frozen=True, slots=True)
class ContractSurface:
    """One indexed contract or export surface."""

    path: str
    commit_sha: str
    symbol: str | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class ContractIndex:
    """Indexed contract surfaces for a repository at a pinned commit."""

    commit_sha: str
    openapi: tuple[ContractSurface, ...]
    graphql: tuple[ContractSurface, ...]
    protobuf: tuple[ContractSurface, ...]
    exports: tuple[ContractSurface, ...]


_OPENAPI_GLOBS = ("openapi.yaml", "openapi.yml", "openapi.json")
_GRAPHQL_GLOBS = ("schema.graphql", "schema.gql")
_PROTO_GLOBS = (".proto",)
_EXPORT_INIT_GLOB = "__init__.py"

_OPERATION_ID_RE = re.compile(r"operationId:\s*(\S+)")
_GRAPHQL_TYPE_RE = re.compile(r"^type\s+(\w+)", re.MULTILINE)
_PROTO_SERVICE_RE = re.compile(r"service\s+(\w+)")


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _index_openapi(path: Path, *, root: Path, commit_sha: str) -> list[ContractSurface]:
    rel = _rel(path, root)
    text = path.read_text(encoding="utf-8")
    symbols = _OPERATION_ID_RE.findall(text)
    if symbols:
        return [
            ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="openapi")
            for symbol in symbols
        ]
    return [ContractSurface(path=rel, commit_sha=commit_sha, kind="openapi")]


def _index_graphql(path: Path, *, root: Path, commit_sha: str) -> list[ContractSurface]:
    rel = _rel(path, root)
    text = path.read_text(encoding="utf-8")
    symbols = _GRAPHQL_TYPE_RE.findall(text)
    if symbols:
        return [
            ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="graphql")
            for symbol in symbols
        ]
    return [ContractSurface(path=rel, commit_sha=commit_sha, kind="graphql")]


def _index_protobuf(path: Path, *, root: Path, commit_sha: str) -> list[ContractSurface]:
    rel = _rel(path, root)
    text = path.read_text(encoding="utf-8")
    symbols = _PROTO_SERVICE_RE.findall(text)
    if symbols:
        return [
            ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="protobuf")
            for symbol in symbols
        ]
    return [ContractSurface(path=rel, commit_sha=commit_sha, kind="protobuf")]


def _index_exports(path: Path, *, root: Path, commit_sha: str) -> list[ContractSurface]:
    rel = _rel(path, root)
    text = path.read_text(encoding="utf-8")
    symbols: list[str] = []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    for elt in node.value.elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            symbols.append(elt.value)
    return [
        ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="export")
        for symbol in symbols
    ]


def index_contracts(*, repo_root: Path, commit_sha: str) -> ContractIndex:
    """Index OpenAPI, GraphQL, protobuf, and Python export surfaces."""
    openapi: list[ContractSurface] = []
    graphql: list[ContractSurface] = []
    protobuf: list[ContractSurface] = []
    exports: list[ContractSurface] = []

    for path in sorted(repo_root.rglob("*")):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name in _OPENAPI_GLOBS:
            openapi.extend(_index_openapi(path, root=repo_root, commit_sha=commit_sha))
        elif name in _GRAPHQL_GLOBS:
            graphql.extend(_index_graphql(path, root=repo_root, commit_sha=commit_sha))
        elif name.endswith(_PROTO_GLOBS[0]):
            protobuf.extend(_index_protobuf(path, root=repo_root, commit_sha=commit_sha))
        elif name == _EXPORT_INIT_GLOB and "src" in path.parts:
            exports.extend(_index_exports(path, root=repo_root, commit_sha=commit_sha))

    return ContractIndex(
        commit_sha=commit_sha,
        openapi=tuple(openapi),
        graphql=tuple(graphql),
        protobuf=tuple(protobuf),
        exports=tuple(exports),
    )


__all__ = ["ContractIndex", "ContractSurface", "index_contracts"]
