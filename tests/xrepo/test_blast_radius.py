"""DG6 cross-repo blast radius — contract change to dependent repos (G12).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG6).
Implementation: **DG6.2** — ``mergecraft.xrepo.blast_radius``.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.xrepo.support import (
    import_xrepo_module,
    write_contract_fixture_repo,
    write_cross_repo_consumer_fixture,
    write_linked_repos_manifest,
)


@pytest.mark.xfail(reason="green after DG6.2: cross-repo blast radius", strict=False)
def test_changed_contract_resolves_to_dependent_repos(tmp_path: Path) -> None:
    """A changed contract in one linked repo resolves to dependent repos."""
    contracts_root = tmp_path / "api-contracts"
    consumer_root = tmp_path / "web-client"
    contracts_commit = write_contract_fixture_repo(contracts_root)
    consumer_commit = write_cross_repo_consumer_fixture(
        contracts_root=contracts_root,
        consumer_root=consumer_root,
        contracts_commit=contracts_commit,
    )

    primary_root = tmp_path / "primary"
    primary_root.mkdir()
    write_linked_repos_manifest(
        primary_root,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": contracts_commit},
            {"owner": "acme", "name": "web-client", "commit": consumer_commit},
        ],
    )

    linked_mod = import_xrepo_module("linked_repos")
    blast_mod = import_xrepo_module("blast_radius")
    manifest = linked_mod.parse_manifest(primary_root / ".mergecraft" / "linked-repos.yaml")

    changed = [
        blast_mod.ChangedContract(
            repo="acme/api-contracts",
            commit=contracts_commit,
            path="openapi.yaml",
            kind="openapi",
            operation_id="listUsers",
        )
    ]
    impacts = blast_mod.resolve_cross_repo_dependents(
        changed_contracts=changed,
        manifest=manifest,
        repo_roots={
            "api-contracts": contracts_root,
            "web-client": consumer_root,
        },
    )

    dependent_repos = {impact.repo for impact in impacts}
    assert "acme/web-client" in dependent_repos or "web-client" in dependent_repos
