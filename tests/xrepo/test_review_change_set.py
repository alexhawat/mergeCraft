"""U11 / TB-D11-D12 — the linked-repo change set is pin movement (TB1).

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB1).

Today ``_changed_from_index`` turns **every** indexed surface into a
``ChangedContract``, so the findings say a consumer is affected by a contract
change the PR never made. The honest change source is pin movement: a PR changes
a linked contract only by moving a pin in ``.mergecraft/linked-repos.yaml``.

Locked contracts:

* **TB-D11** — for each granted entry whose pin differs between the base manifest
  and the head manifest, only surfaces whose paths differ between the two pins
  are ``ChangedContract``s. Unmoved or newly added entries contribute none.
  Previous pin unreachable → omission, not a full-index report. An explicit CLI
  ``producer=`` keeps whole-index semantics.
* **TB-D12** — every linked-repo omission is in the payload
  (``linkedRepoOmitted: [{repo, reason}]`` alongside findings).

Reconciled after TB5 — the suite is green with no RED markers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from tests.xrepo.support import (
    git_commit_all,
    git_init_repo,
    write_contract_fixture_repo,
    write_linked_repos_manifest,
)

from mergecraft.review.linked_repos import attach_linked_repo_review
from mergecraft.xrepo.linked_repos import LinkedRepoEntry, LinkedReposManifest
from mergecraft.xrepo.review import review_linked_repos

if TYPE_CHECKING:
    from pathlib import Path

_ALL_SURFACES = ("openapi.yaml", "schema.graphql", "service.proto", "src/demo/__init__.py")


def _consumer_repo(consumer_root: Path, *, contracts_commit: str) -> str:
    """A consumer that references every contract surface the producer exposes."""
    consumer_root.mkdir(parents=True)
    (consumer_root / "README.md").write_text(
        "Consumes acme/api-contracts@"
        f"{contracts_commit} openapi /users schema.graphql service.proto public_helper\n",
        encoding="utf-8",
    )
    git_init_repo(consumer_root)
    return git_commit_all(consumer_root)


def _manifest(*pins: tuple[str, str, str]) -> LinkedReposManifest:
    return LinkedReposManifest(
        repos=tuple(
            LinkedRepoEntry(owner=owner, name=name, commit=commit) for owner, name, commit in pins
        )
    )


def _moved_pin_fixture(tmp_path: Path) -> dict[str, Any]:
    """Producer at two pins (openapi changed), consumer pinned, primary manifest."""
    producer = tmp_path / "api-contracts"
    consumer = tmp_path / "web-client"
    primary = tmp_path / "primary"
    primary.mkdir()

    first_pin = write_contract_fixture_repo(producer)
    (producer / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Demo API\n  version: 2.0.0\n"
        "paths:\n  /accounts:\n    get:\n      operationId: listAccounts\n"
        "      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    second_pin = git_commit_all(producer)
    consumer_pin = _consumer_repo(consumer, contracts_commit=first_pin)

    write_linked_repos_manifest(
        primary,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": second_pin},
            {"owner": "acme", "name": "web-client", "commit": consumer_pin},
        ],
    )
    git_init_repo(primary)
    git_commit_all(primary)
    return {
        "primary": primary,
        "first_pin": first_pin,
        "second_pin": second_pin,
        "consumer_pin": consumer_pin,
        "grant": frozenset({"acme/api-contracts", "acme/web-client"}),
    }


def test_unmoved_pin_yields_zero_findings(tmp_path: Path) -> None:
    """TB-D11 — a PR that does not move a pin changes no linked contract."""
    fixture = _moved_pin_fixture(tmp_path)
    base = _manifest(
        ("acme", "api-contracts", fixture["second_pin"]),
        ("acme", "web-client", fixture["consumer_pin"]),
    )

    review = review_linked_repos(
        repo_root=fixture["primary"],
        base_manifest=base,
        authorized_repos=fixture["grant"],
    )

    assert review.findings == ()


def test_moved_pin_reports_only_surfaces_changed_between_pins(tmp_path: Path) -> None:
    """TB-D11 — only the openapi surface differs between the two pins."""
    fixture = _moved_pin_fixture(tmp_path)
    base = _manifest(
        ("acme", "api-contracts", fixture["first_pin"]),
        ("acme", "web-client", fixture["consumer_pin"]),
    )

    review = review_linked_repos(
        repo_root=fixture["primary"],
        base_manifest=base,
        authorized_repos=fixture["grant"],
    )

    paths = {finding.impact.changed_contract.path for finding in review.findings}
    assert paths == {"openapi.yaml"}, f"unexpected changed surfaces: {paths}"


def test_unchanged_surfaces_are_not_reported_as_changed(tmp_path: Path) -> None:
    """TB-D11 — graphql/proto/exports are identical at both pins."""
    fixture = _moved_pin_fixture(tmp_path)
    base = _manifest(
        ("acme", "api-contracts", fixture["first_pin"]),
        ("acme", "web-client", fixture["consumer_pin"]),
    )

    review = review_linked_repos(
        repo_root=fixture["primary"],
        base_manifest=base,
        authorized_repos=fixture["grant"],
    )

    paths = {finding.impact.changed_contract.path for finding in review.findings}
    assert paths.isdisjoint({"schema.graphql", "service.proto", "src/demo/__init__.py"})


def test_explicit_producer_keeps_whole_index_semantics(tmp_path: Path) -> None:
    """Guard — ``mergecraft xrepo explain --producer`` is an operator assertion.

    The grant is left to default (every manifest entry) so this pins the
    producer semantics, not the grant matching that TB5 changes.
    """
    fixture = _moved_pin_fixture(tmp_path)

    review = review_linked_repos(
        repo_root=fixture["primary"],
        producer="acme/api-contracts",
    )

    paths = {finding.impact.changed_contract.path for finding in review.findings}
    assert paths, "an explicit producer keeps the whole-index report"
    assert len(paths) > 1


def test_ungranted_entry_appears_in_linked_repo_omitted(tmp_path: Path) -> None:
    """TB-D12 — 'nothing was checked' is distinguishable from 'no findings'."""
    primary = tmp_path / "primary"
    contracts = tmp_path / "api-contracts"
    secrets = tmp_path / "secrets-store"
    primary.mkdir()
    secrets.mkdir()
    git_init_repo(secrets)
    (secrets / "secret.txt").write_text("classified\n", encoding="utf-8")
    secret_commit = git_commit_all(secrets)
    contracts_commit = write_contract_fixture_repo(contracts)
    write_linked_repos_manifest(
        primary,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": contracts_commit},
            {"owner": "acme", "name": "secrets-store", "commit": secret_commit},
        ],
    )
    git_init_repo(primary)
    git_commit_all(primary)

    payload = attach_linked_repo_review(primary, authorized_repos=frozenset({"acme/api-contracts"}))

    assert payload is not None
    omitted = payload.get("linkedRepoOmitted")
    assert omitted, "an ungranted entry must be recorded, not silently skipped"
    assert any("secrets-store" in str(row.get("repo", "")) for row in omitted)
    assert all(row.get("reason") for row in omitted)


def test_unreachable_previous_pin_is_an_omission_not_a_full_index(tmp_path: Path) -> None:
    """TB-D11/D12 — a base pin this checkout cannot resolve omits, never reports."""
    fixture = _moved_pin_fixture(tmp_path)
    base = _manifest(
        ("acme", "api-contracts", "f" * 40),
        ("acme", "web-client", fixture["consumer_pin"]),
    )

    payload = attach_linked_repo_review(
        fixture["primary"],
        authorized_repos=fixture["grant"],
        base_manifest=base,
    )

    assert payload is not None
    assert payload["linkedRepoFindings"] == []
    omitted = payload.get("linkedRepoOmitted")
    assert omitted, "an unreachable previous pin must be recorded as an omission"
    reasons = " ".join(str(row.get("reason", "")).lower() for row in omitted)
    assert "pin" in reasons or "unreachable" in reasons
