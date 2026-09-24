"""F4 / TB-D11-D12 — the base linked-repo manifest: absent vs unreadable.

Wave plan: ``.ignorelocal/waves/40-trust-boundaries-wave-plan.md`` (TB6, F4).

``_base_linked_repo_manifest`` distinguishes a manifest that is genuinely
**absent** at ``origin/<base>`` (every head entry is newly added and contributes
no change) from one that **exists but cannot be decoded or parsed** (the
movement baseline is unknown, so every otherwise-reviewable entry is an omission
with a reason — never a silent zero-finding report).

These tests exercise the **real git read path** (``_base_linked_repo_manifest``
over a checkout with an ``origin/<base>`` ref) and feed the lookup into
``attach_linked_repo_review``, so the glue between the read and the payload is
covered, not just a hand-built manifest.
"""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

from tests.xrepo.support import (
    git_commit_all,
    git_init_repo,
    write_contract_fixture_repo,
    write_linked_repos_manifest,
)

from mergecraft.mcp.checkout import _base_linked_repo_manifest
from mergecraft.review.linked_repos import attach_linked_repo_review

if TYPE_CHECKING:
    from pathlib import Path

_UNREADABLE_FRAGMENT = "unreadable"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _head_sha(cwd: Path) -> str:
    return _git(cwd, "rev-parse", "HEAD")


def _primary_clone(tmp_path: Path) -> Path:
    """A clone whose ``origin/main`` is the base branch of a work repo."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init")
    _git(work, "config", "user.email", "test@example.com")
    _git(work, "config", "user.name", "Test")
    (work / "README.md").write_text("base\n", encoding="utf-8")
    _git(work, "add", "README.md")
    _git(work, "commit", "-m", "base")
    _git(work, "branch", "-M", "main")
    _git(work, "clone", "--bare", str(work), str(origin))
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", str(origin), str(clone))
    # The clone gets its own identity: every commit below runs with ``clone`` as
    # cwd, and CI runners have no global ``user.email``/``user.name`` to fall
    # back on (``git commit`` would exit 128).
    _git(clone, "config", "user.email", "test@example.com")
    _git(clone, "config", "user.name", "Test")
    return clone


def _commit_head_manifest(clone: Path, *, repos: list[dict[str, str]]) -> None:
    """Add the head manifest on a ``feature`` branch (``origin/main`` untouched)."""
    _git(clone, "checkout", "-b", "feature")
    write_linked_repos_manifest(clone, repos=repos)
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "head manifest")


def _set_origin_ref(clone: Path, ref: str, sha: str) -> None:
    _git(clone, "update-ref", f"refs/remotes/origin/{ref}", sha)


def _consumer_repo(consumer_root: Path, *, contracts_commit: str) -> str:
    consumer_root.mkdir(parents=True)
    (consumer_root / "README.md").write_text(
        "Consumes acme/api-contracts@"
        f"{contracts_commit} openapi /users schema.graphql service.proto public_helper\n",
        encoding="utf-8",
    )
    git_init_repo(consumer_root)
    return git_commit_all(consumer_root)


def _moved_openapi(producer: Path) -> str:
    (producer / "openapi.yaml").write_text(
        "openapi: 3.0.0\ninfo:\n  title: Demo API\n  version: 2.0.0\n"
        "paths:\n  /accounts:\n    get:\n      operationId: listAccounts\n"
        "      responses:\n        '200':\n          description: ok\n",
        encoding="utf-8",
    )
    return git_commit_all(producer)


# ── Unit: the three lookup outcomes over a real checkout ─────────────────────


def test_no_base_ref_returns_an_empty_lookup(tmp_path: Path) -> None:
    """Guard — with no base ref there is nothing to read, and no omission."""
    clone = _primary_clone(tmp_path)

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="")

    assert lookup.manifest.repos == ()
    assert lookup.unreadable_reason is None


def test_absent_base_manifest_reads_as_empty_without_a_reason(tmp_path: Path) -> None:
    """F4 — ``origin/main`` has no manifest: head entries are newly added."""
    clone = _primary_clone(tmp_path)

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")

    assert lookup.manifest.repos == ()
    assert lookup.unreadable_reason is None


def test_corrupt_base_manifest_is_marked_unreadable(tmp_path: Path) -> None:
    """F4 — an existing-but-unparseable manifest sets ``unreadable_reason``."""
    clone = _primary_clone(tmp_path)
    (clone / ".mergecraft").mkdir()
    (clone / ".mergecraft" / "linked-repos.yaml").write_text(
        "repos: not-a-list\n", encoding="utf-8"
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "corrupt base manifest")
    _set_origin_ref(clone, "main", _head_sha(clone))

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")

    assert lookup.manifest.repos == ()
    assert lookup.unreadable_reason is not None
    assert _UNREADABLE_FRAGMENT in lookup.unreadable_reason.lower()


def test_valid_base_manifest_is_parsed(tmp_path: Path) -> None:
    """F4 — a readable base manifest is the pin-movement baseline."""
    clone = _primary_clone(tmp_path)
    write_linked_repos_manifest(
        clone,
        repos=[{"owner": "acme", "name": "api-contracts", "commit": "a" * 40}],
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "base manifest")
    _set_origin_ref(clone, "main", _head_sha(clone))

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")

    assert lookup.unreadable_reason is None
    assert [(entry.slug, entry.commit) for entry in lookup.manifest.repos] == [
        ("acme/api-contracts", "a" * 40)
    ]


def test_binary_base_manifest_is_marked_unreadable(tmp_path: Path) -> None:
    """F4 — a blob that cannot be decoded is unreadable, not silently absent."""
    clone = _primary_clone(tmp_path)
    (clone / ".mergecraft").mkdir()
    (clone / ".mergecraft" / "linked-repos.yaml").write_bytes(b"repos:\x00\x00\n")
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "binary base manifest")
    _set_origin_ref(clone, "main", _head_sha(clone))

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")

    assert lookup.manifest.repos == ()
    assert lookup.unreadable_reason is not None


# ── Integration: the lookup feeds the linked-repo payload ────────────────────


def test_absent_base_manifest_yields_no_omission(tmp_path: Path) -> None:
    """F4 — a manifest first added by the PR is not an omission."""
    producer = tmp_path / "api-contracts"
    pin = write_contract_fixture_repo(producer)
    clone = _primary_clone(tmp_path)
    _commit_head_manifest(
        clone,
        repos=[{"owner": "acme", "name": "api-contracts", "commit": pin}],
    )

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")
    payload = attach_linked_repo_review(
        clone,
        authorized_repos=frozenset({"acme/api-contracts"}),
        base_manifest=lookup.manifest,
        base_manifest_error=lookup.unreadable_reason,
    )

    assert payload is not None
    assert payload["linkedRepoFindings"] == []
    assert payload.get("linkedRepoOmitted") == []


def test_unreadable_base_manifest_omits_every_reviewable_entry(tmp_path: Path) -> None:
    """F4 — an unreadable base manifest is an omission per entry, zero findings."""
    producer = tmp_path / "api-contracts"
    pin = write_contract_fixture_repo(producer)
    clone = _primary_clone(tmp_path)
    (clone / ".mergecraft").mkdir()
    (clone / ".mergecraft" / "linked-repos.yaml").write_text(
        "repos: not-a-list\n", encoding="utf-8"
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "corrupt base manifest")
    _set_origin_ref(clone, "main", _head_sha(clone))
    _commit_head_manifest(
        clone,
        repos=[{"owner": "acme", "name": "api-contracts", "commit": pin}],
    )

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")
    assert lookup.unreadable_reason is not None

    payload = attach_linked_repo_review(
        clone,
        authorized_repos=frozenset({"acme/api-contracts"}),
        base_manifest=lookup.manifest,
        base_manifest_error=lookup.unreadable_reason,
    )

    assert payload is not None
    assert payload["linkedRepoFindings"] == []
    omitted = payload.get("linkedRepoOmitted") or []
    assert [row["repo"] for row in omitted] == ["acme/api-contracts"]
    assert all(row["reason"] == lookup.unreadable_reason for row in omitted)


# ── TB6: a failed base fetch is an omission, not a silent zero ───────────────


def test_unresolved_base_ref_with_a_fetch_failure_marks_the_manifest_unreadable(
    tmp_path: Path,
) -> None:
    """TB6 — a base fetch that failed is unknown, not empty: reason names the failure."""
    clone = _primary_clone(tmp_path)

    lookup = _base_linked_repo_manifest(
        cwd=str(clone),
        base_ref="release",  # never fetched → ``origin/release`` does not resolve
        base_fetch_failure="could not fetch origin/release",
    )

    assert lookup.manifest.repos == ()
    assert lookup.unreadable_reason is not None
    assert "could not fetch origin/release" in lookup.unreadable_reason
    assert "resolve" in lookup.unreadable_reason.lower()


def test_failed_base_fetch_omits_every_reviewable_entry(tmp_path: Path) -> None:
    """TB6 — an unresolvable base ref yields ``linkedRepoOmitted`` per entry, zero findings."""
    producer = tmp_path / "api-contracts"
    pin = write_contract_fixture_repo(producer)
    clone = _primary_clone(tmp_path)
    _commit_head_manifest(
        clone,
        repos=[{"owner": "acme", "name": "api-contracts", "commit": pin}],
    )

    lookup = _base_linked_repo_manifest(
        cwd=str(clone),
        base_ref="release",
        base_fetch_failure="could not fetch origin/release",
    )
    assert lookup.unreadable_reason is not None

    payload = attach_linked_repo_review(
        clone,
        authorized_repos=frozenset({"acme/api-contracts"}),
        base_manifest=lookup.manifest,
        base_manifest_error=lookup.unreadable_reason,
    )

    assert payload is not None
    assert payload["linkedRepoFindings"] == []
    omitted = payload.get("linkedRepoOmitted") or []
    assert [row["repo"] for row in omitted] == ["acme/api-contracts"]
    assert all("could not fetch origin/release" in row["reason"] for row in omitted)


def test_absent_manifest_with_no_fetch_failure_stays_omission_free(tmp_path: Path) -> None:
    """F4 guard — a genuinely absent manifest at a resolved base ref is not an omission."""
    producer = tmp_path / "api-contracts"
    pin = write_contract_fixture_repo(producer)
    clone = _primary_clone(tmp_path)
    _commit_head_manifest(
        clone,
        repos=[{"owner": "acme", "name": "api-contracts", "commit": pin}],
    )

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main", base_fetch_failure=None)

    assert lookup.manifest.repos == ()
    assert lookup.unreadable_reason is None

    payload = attach_linked_repo_review(
        clone,
        authorized_repos=frozenset({"acme/api-contracts"}),
        base_manifest=lookup.manifest,
        base_manifest_error=lookup.unreadable_reason,
    )

    assert payload is not None
    assert payload.get("linkedRepoOmitted") == []


def test_valid_base_manifest_drives_the_pin_movement_findings(tmp_path: Path) -> None:
    """F4 — a readable base manifest gives the real change set (non-empty glue)."""
    producer = tmp_path / "api-contracts"
    consumer = tmp_path / "web-client"
    first_pin = write_contract_fixture_repo(producer)
    consumer_pin = _consumer_repo(consumer, contracts_commit=first_pin)
    second_pin = _moved_openapi(producer)
    clone = _primary_clone(tmp_path)
    write_linked_repos_manifest(
        clone,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": first_pin},
            {"owner": "acme", "name": "web-client", "commit": consumer_pin},
        ],
    )
    _git(clone, "add", "-A")
    _git(clone, "commit", "-m", "base manifest")
    _set_origin_ref(clone, "main", _head_sha(clone))
    _commit_head_manifest(
        clone,
        repos=[
            {"owner": "acme", "name": "api-contracts", "commit": second_pin},
            {"owner": "acme", "name": "web-client", "commit": consumer_pin},
        ],
    )

    lookup = _base_linked_repo_manifest(cwd=str(clone), base_ref="main")
    assert lookup.unreadable_reason is None
    assert [entry.commit for entry in lookup.manifest.repos] == [first_pin, consumer_pin]

    payload = attach_linked_repo_review(
        clone,
        authorized_repos=frozenset({"acme/api-contracts", "acme/web-client"}),
        base_manifest=lookup.manifest,
        base_manifest_error=lookup.unreadable_reason,
    )

    assert payload is not None
    paths = {row["path"] for row in payload["linkedRepoFindings"]}
    assert paths == {"openapi.yaml"}, f"unexpected changed surfaces: {paths}"
