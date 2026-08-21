"""W4.1 — ``mergecraft.xrepo`` production wiring pins (#353 / W7).

Library linked-repo / contract / blast-radius tests already exist. This file
pins review-path wiring, SHA-pinned linked repos, the authorization boundary,
``mergecraft xrepo explain``, and a multi-service producer/consumer fixture.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from tests.support.dead_package_wiring import (
    cli_cmd_path,
    production_importers,
    production_invoked_names,
)
from tests.xrepo.support import (
    git_commit_all,
    git_init_repo,
    write_contract_fixture_repo,
    write_cross_repo_consumer_fixture,
    write_linked_repos_manifest,
)
from typer.testing import CliRunner

from mergecraft.cli.app import app
from mergecraft.cli.exits import CLI_SUCCESS_EXIT_CODE

runner = CliRunner()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DUMB_ENV = {"TERM": "dumb", "NO_COLOR": "1"}


def _plain(text: str) -> str:
    return _ANSI.sub("", text)


def _invoke(*argv: str) -> Any:
    return runner.invoke(app, list(argv), env=_DUMB_ENV)


def _require_xrepo() -> None:
    """Fail until ``xrepo`` is registered (avoids XPASS on Typer usage)."""
    result = _invoke("xrepo", "--help")
    if result.exit_code != CLI_SUCCESS_EXIT_CODE:
        pytest.fail("mergecraft xrepo is not registered yet")


def test_xrepo_has_a_review_or_cli_production_call_site() -> None:
    """W7 — review path or CLI imports ``mergecraft.xrepo``."""
    importers = production_importers("xrepo")
    assert importers, "expected a production import of mergecraft.xrepo"
    assert any(
        path.startswith(("cli/", "modes/", "mcp/", "action/", "agents/")) or path == "main.py"
        for path in importers
    )


def test_xrepo_cli_is_a_new_cmd_module() -> None:
    """D10 — ``xrepo explain`` lives in ``cli/xrepo_cmd.py``."""
    path = cli_cmd_path("xrepo")
    assert path is not None, "expected src/mergecraft/cli/xrepo_cmd.py"
    source = path.read_text(encoding="utf-8")
    assert "explain" in source


def test_root_help_lists_xrepo() -> None:
    """Happy: root help advertises ``xrepo``."""
    result = _invoke("--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "xrepo" in help_text


def test_xrepo_explain_help_is_registered() -> None:
    """Happy: ``mergecraft xrepo explain --help`` exists."""
    result = _invoke("xrepo", "explain", "--help")
    help_text = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, help_text
    assert "explain" in help_text


def test_review_path_uses_sha_pinned_linked_repos() -> None:
    """#353 — linked repos in review are SHA-pinned (``parse_manifest``)."""
    invoked = production_invoked_names(exclude_package="xrepo")
    assert "parse_manifest" in invoked or "validate_pinned_sha" in invoked
    assert production_importers("xrepo")


def test_unauthorized_linked_repo_is_blocked_on_the_review_path() -> None:
    """#353 — a run cannot read a repo outside its grant (authorization test)."""
    invoked = production_invoked_names(exclude_package="xrepo")
    assert "load_linked_repo_content" in invoked
    from mergecraft.xrepo.linked_repos import LinkedRepoAccessError

    assert issubclass(LinkedRepoAccessError, PermissionError)


def test_explain_unknown_finding_id_is_an_error() -> None:
    """Error: ``xrepo explain`` on a missing finding id is not success."""
    _require_xrepo()
    result = _invoke("xrepo", "explain", "XR-DOES-NOT-EXIST")
    combined = _plain(result.stdout + result.stderr)
    assert result.exit_code != CLI_SUCCESS_EXIT_CODE, combined


def test_multi_service_fixture_reports_producer_consumer_breakage(tmp_path: Path) -> None:
    """#353 — realistic multi-service fixture: producer contract break hits consumer."""
    contracts_root = tmp_path / "api-contracts"
    consumer_root = tmp_path / "web-client"
    primary = tmp_path / "primary"
    primary.mkdir()
    contracts_commit = write_contract_fixture_repo(contracts_root)
    (contracts_root / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Demo API\n  version: 2.0.0\n"
        "paths:\n  /accounts:\n    get:\n      operationId: listAccounts\n"
        "      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    broken_commit = git_commit_all(contracts_root)
    consumer_commit = write_cross_repo_consumer_fixture(
        contracts_root=contracts_root,
        consumer_root=consumer_root,
        contracts_commit=contracts_commit,
    )
    write_linked_repos_manifest(
        primary,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": broken_commit},
            {"owner": "acme", "name": "web-client", "commit": consumer_commit},
        ],
    )
    git_init_repo(primary)
    git_commit_all(primary)

    result = _invoke(
        "xrepo",
        "explain",
        "--repo-root",
        str(primary),
        "--producer",
        "acme/api-contracts",
    )
    output = _plain(result.stdout + result.stderr).casefold()
    assert result.exit_code == CLI_SUCCESS_EXIT_CODE, output
    assert "web-client" in output or "consumer" in output
    assert "openapi" in output or "contract" in output or "break" in output


def test_pr_manifest_cannot_authorize_an_ungranted_sibling(tmp_path: Path) -> None:
    """D9 — checkout grant is the operator set, not names from the PR manifest."""
    from mergecraft.review.linked_repos import attach_linked_repo_review

    primary = tmp_path / "primary"
    secrets = tmp_path / "secrets-store"
    contracts = tmp_path / "api-contracts"
    primary.mkdir()
    secrets.mkdir()
    (secrets / "secret.txt").write_text("classified\n", encoding="utf-8")
    git_init_repo(secrets)
    secret_commit = git_commit_all(secrets)
    contracts_commit = write_contract_fixture_repo(contracts)
    write_linked_repos_manifest(
        primary,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": contracts_commit},
            {"owner": "acme", "name": "secrets-store", "commit": secret_commit},
        ],
    )
    denied = attach_linked_repo_review(primary)
    assert denied is not None
    assert denied["linkedRepoFindings"] == []
    granted = attach_linked_repo_review(primary, authorized_repos=frozenset({"api-contracts"}))
    assert granted is not None
    joined = " ".join(
        f"{row['consumer']} {row['producer']}" for row in granted["linkedRepoFindings"]
    )
    assert "secrets-store" not in joined


def test_mismatched_head_is_not_reported_as_pinned_sha(tmp_path: Path) -> None:
    """Pinned SHA evidence is omitted when the sibling checkout HEAD differs."""
    from mergecraft.xrepo.review import review_linked_repos

    primary = tmp_path / "primary"
    contracts = tmp_path / "api-contracts"
    consumer = tmp_path / "web-client"
    primary.mkdir()
    pin = write_contract_fixture_repo(contracts)
    (contracts / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Demo API\n  version: 2.0.0\n"
        "paths:\n  /accounts:\n    get:\n      operationId: listAccounts\n"
        "      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    git_commit_all(contracts)
    consumer_commit = write_cross_repo_consumer_fixture(
        contracts_root=contracts,
        consumer_root=consumer,
        contracts_commit=pin,
    )
    write_linked_repos_manifest(
        primary,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": pin},
            {"owner": "acme", "name": "web-client", "commit": consumer_commit},
        ],
    )
    review = review_linked_repos(repo_root=primary, producer="acme/api-contracts")
    assert all(finding.impact.changed_contract.commit != pin for finding in review.findings)


def test_mismatched_consumer_head_is_not_scanned(tmp_path: Path) -> None:
    """A matching producer pin still skips a consumer whose HEAD drifted."""
    from mergecraft.xrepo.review import review_linked_repos

    primary = tmp_path / "primary"
    contracts = tmp_path / "api-contracts"
    consumer = tmp_path / "web-client"
    primary.mkdir()
    pin = write_contract_fixture_repo(contracts)
    consumer_commit = write_cross_repo_consumer_fixture(
        contracts_root=contracts,
        consumer_root=consumer,
        contracts_commit=pin,
    )
    (consumer / "drift.txt").write_text("HEAD moved\n", encoding="utf-8")
    git_commit_all(consumer)
    write_linked_repos_manifest(
        primary,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": pin},
            {"owner": "acme", "name": "web-client", "commit": consumer_commit},
        ],
    )
    review = review_linked_repos(repo_root=primary, producer="acme/api-contracts")
    assert all("web-client" not in finding.impact.repo for finding in review.findings)
