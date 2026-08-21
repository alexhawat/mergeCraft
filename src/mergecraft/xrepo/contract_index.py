"""Contract surface indexing — OpenAPI, GraphQL, protobuf, and export symbols."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

from mergecraft.context.repo_paths import git_ls_tree_paths, git_show_text
from mergecraft.utils.bounded_text import (
    MAX_INDEX_TEXT_BYTES,
    iter_indexable_files,
    read_bounded_text,
)


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


def _read_contract_text(path: Path) -> str | None:
    return read_bounded_text(path)


def _index_openapi_text(rel: str, text: str, commit_sha: str) -> list[ContractSurface]:
    symbols = _OPERATION_ID_RE.findall(text)
    if symbols:
        return [
            ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="openapi")
            for symbol in symbols
        ]
    return [ContractSurface(path=rel, commit_sha=commit_sha, kind="openapi")]


def _index_graphql_text(rel: str, text: str, commit_sha: str) -> list[ContractSurface]:
    symbols = _GRAPHQL_TYPE_RE.findall(text)
    if symbols:
        return [
            ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="graphql")
            for symbol in symbols
        ]
    return [ContractSurface(path=rel, commit_sha=commit_sha, kind="graphql")]


def _index_protobuf_text(rel: str, text: str, commit_sha: str) -> list[ContractSurface]:
    symbols = _PROTO_SERVICE_RE.findall(text)
    if symbols:
        return [
            ContractSurface(path=rel, commit_sha=commit_sha, symbol=symbol, kind="protobuf")
            for symbol in symbols
        ]
    return [ContractSurface(path=rel, commit_sha=commit_sha, kind="protobuf")]


def _index_exports_text(rel: str, text: str, commit_sha: str) -> list[ContractSurface]:
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


def _surfaces_for_text(*, rel: str, text: str, commit_sha: str) -> list[ContractSurface]:
    name = Path(rel).name.lower()
    parts = Path(rel).parts
    if name in _OPENAPI_GLOBS:
        return _index_openapi_text(rel, text, commit_sha)
    if name in _GRAPHQL_GLOBS:
        return _index_graphql_text(rel, text, commit_sha)
    if name.endswith(_PROTO_GLOBS[0]):
        return _index_protobuf_text(rel, text, commit_sha)
    if name == _EXPORT_INIT_GLOB and "src" in parts:
        return _index_exports_text(rel, text, commit_sha)
    return []


def _collect_index(commit_sha: str, surfaces: list[ContractSurface]) -> ContractIndex:
    openapi = tuple(item for item in surfaces if item.kind == "openapi")
    graphql = tuple(item for item in surfaces if item.kind == "graphql")
    protobuf = tuple(item for item in surfaces if item.kind == "protobuf")
    exports = tuple(item for item in surfaces if item.kind == "export")
    return ContractIndex(
        commit_sha=commit_sha,
        openapi=openapi,
        graphql=graphql,
        protobuf=protobuf,
        exports=exports,
    )


def index_contracts(*, repo_root: Path, commit_sha: str) -> ContractIndex:
    """Index OpenAPI, GraphQL, protobuf, and Python export surfaces on disk."""
    surfaces: list[ContractSurface] = []
    for path in iter_indexable_files(repo_root):
        text = _read_contract_text(path)
        if text is None:
            continue
        surfaces.extend(
            _surfaces_for_text(rel=_rel(path, repo_root), text=text, commit_sha=commit_sha)
        )
    return _collect_index(commit_sha, surfaces)


def index_contracts_at_commit(*, repo_root: Path, commit_sha: str) -> ContractIndex:
    """Index contract surfaces from the pinned git object, not the working tree."""
    surfaces: list[ContractSurface] = []
    for rel in git_ls_tree_paths(repo_root, commit_sha):
        text = git_show_text(repo_root, commit_sha, rel)
        if text is None or len(text.encode("utf-8", errors="replace")) > MAX_INDEX_TEXT_BYTES:
            continue
        surfaces.extend(_surfaces_for_text(rel=rel, text=text, commit_sha=commit_sha))
    return _collect_index(commit_sha, surfaces)


__all__ = [
    "ContractIndex",
    "ContractSurface",
    "index_contracts",
    "index_contracts_at_commit",
]
