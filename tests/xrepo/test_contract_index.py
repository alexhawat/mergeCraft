"""DG6 contract index — OpenAPI, GraphQL, protobuf, exports (G12).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG6).
Implementation: **DG6.2** — ``mergecraft.xrepo.contract_index``.
"""

from __future__ import annotations

from pathlib import Path

from tests.context.support import git_commit_all
from tests.xrepo.support import import_xrepo_module, write_contract_fixture_repo

from mergecraft.utils.bounded_text import MAX_INDEX_TEXT_BYTES


def test_openapi_graphql_protobuf_and_exports_are_indexed(tmp_path: Path) -> None:
    """Contract indexing surfaces OpenAPI, GraphQL, protobuf, and export symbols."""
    repo_root = tmp_path / "contracts"
    commit_sha = write_contract_fixture_repo(repo_root)

    contract_mod = import_xrepo_module("contract_index")
    index = contract_mod.index_contracts(repo_root=repo_root, commit_sha=commit_sha)

    openapi_paths = {item.path for item in index.openapi}
    graphql_paths = {item.path for item in index.graphql}
    protobuf_paths = {item.path for item in index.protobuf}
    export_symbols = {item.symbol for item in index.exports}

    assert "openapi.yaml" in openapi_paths
    assert "schema.graphql" in graphql_paths
    assert "service.proto" in protobuf_paths
    assert "public_helper" in export_symbols


def test_index_at_commit_reads_git_object_not_worktree(tmp_path: Path) -> None:
    """Pinned-commit indexing ignores uncommitted contract files on disk."""
    repo_root = tmp_path / "contracts"
    commit_sha = write_contract_fixture_repo(repo_root)
    (repo_root / "openapi.json").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Sneaky\n  version: 0.0.1\n"
        "paths:\n  /sneak:\n    get:\n      operationId: sneakyOp\n"
        "      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    contract_mod = import_xrepo_module("contract_index")
    disk = contract_mod.index_contracts(repo_root=repo_root, commit_sha=commit_sha)
    pinned = contract_mod.index_contracts_at_commit(repo_root=repo_root, commit_sha=commit_sha)
    assert "sneakyOp" in {item.symbol for item in disk.openapi}
    assert "sneakyOp" not in {item.symbol for item in pinned.openapi}


def test_index_at_commit_skips_oversize_blobs_without_loading(tmp_path: Path) -> None:
    """Pinned scans skip blobs over the byte budget instead of indexing them."""
    repo_root = tmp_path / "contracts"
    write_contract_fixture_repo(repo_root)
    huge = "operationId: hugeOp\n" + ("x" * (MAX_INDEX_TEXT_BYTES + 1))
    (repo_root / "openapi.yaml").write_text(huge, encoding="utf-8")
    commit_sha = git_commit_all(repo_root, "oversized contract")

    contract_mod = import_xrepo_module("contract_index")
    pinned = contract_mod.index_contracts_at_commit(repo_root=repo_root, commit_sha=commit_sha)
    assert "hugeOp" not in {item.symbol for item in pinned.openapi}
    assert "listUsers" not in {item.symbol for item in pinned.openapi}
