"""Shared helpers for cross-repo intelligence tests (DG6.1 RED)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.analyzers.support import import_module
from tests.context.support import (
    fenced_blocks,
    git_commit_all,
    git_init_repo,
    git_run,
)

FENCE_OPEN = "<<<UNTRUSTED-MERGECRAFT-CONTENT"


def import_xrepo_module(name: str) -> Any:
    """Lazy import for ``mergecraft.xrepo.*`` symbols."""
    return import_module(f"mergecraft.xrepo.{name}")


def import_requirements_module(name: str) -> Any:
    """Lazy import for ``mergecraft.requirements.*`` symbols."""
    return import_module(f"mergecraft.requirements.{name}")


def write_linked_repos_manifest(
    root: Path,
    *,
    repos: list[dict[str, str]],
) -> Path:
    """Write a linked-repo manifest under ``.mergecraft/linked-repos.yaml``."""
    manifest_dir = root / ".mergecraft"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    lines = ["repos:"]
    for repo in repos:
        lines.append(f"  - owner: {repo['owner']}")
        lines.append(f"    name: {repo['name']}")
        lines.append(f"    commit: {repo['commit']}")
    manifest_path = manifest_dir / "linked-repos.yaml"
    manifest_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest_path


def write_contract_fixture_repo(root: Path) -> str:
    """Lay down OpenAPI, GraphQL, protobuf, and export surfaces for indexing tests."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Demo API\n  version: 1.0.0\n"
        "paths:\n  /users:\n    get:\n      operationId: listUsers\n      responses:\n"
        "        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    (root / "schema.graphql").write_text(
        "type Query {\n  users: [User!]!\n}\n\ntype User {\n  id: ID!\n  name: String!\n}\n",
        encoding="utf-8",
    )
    (root / "service.proto").write_text(
        'syntax = "proto3";\n\npackage demo.v1;\n\nservice UserService {\n'
        "  rpc ListUsers(ListUsersRequest) returns (ListUsersResponse);\n}\n",
        encoding="utf-8",
    )
    package = root / "src" / "demo"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        '__all__ = ["public_helper"]\n\n\ndef public_helper() -> str:\n    return "ok"\n',
        encoding="utf-8",
    )
    git_init_repo(root)
    return git_commit_all(root)


def write_cross_repo_consumer_fixture(
    *,
    contracts_root: Path,
    consumer_root: Path,
    contracts_commit: str,
) -> str:
    """Create a consumer repo that references the contracts repo."""
    consumer_root.mkdir(parents=True, exist_ok=True)
    (consumer_root / "README.md").write_text(
        f"Consumes acme/api-contracts@{contracts_commit} openapi /users\n",
        encoding="utf-8",
    )
    (consumer_root / "client.py").write_text(
        'def fetch_users() -> list[str]:\n    return ["demo"]\n',
        encoding="utf-8",
    )
    git_init_repo(consumer_root)
    return git_commit_all(consumer_root)


__all__ = [
    "FENCE_OPEN",
    "fenced_blocks",
    "git_commit_all",
    "git_init_repo",
    "git_run",
    "import_requirements_module",
    "import_xrepo_module",
    "write_contract_fixture_repo",
    "write_cross_repo_consumer_fixture",
    "write_linked_repos_manifest",
]
