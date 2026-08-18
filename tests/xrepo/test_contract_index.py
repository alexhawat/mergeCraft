"""DG6 contract index — OpenAPI, GraphQL, protobuf, exports (G12).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG6).
Implementation: **DG6.2** — ``mergecraft.xrepo.contract_index``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.xrepo.support import import_xrepo_module, write_contract_fixture_repo


@pytest.mark.xfail(reason="green after DG6.2: contract surface indexing", strict=False)
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
