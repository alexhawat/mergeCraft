"""Attach SHA-pinned linked-repo review to the ordinary checkout path (#353).

Output-only: never writes into the reviewed tree.
"""

from __future__ import annotations

import os
from pathlib import Path  # noqa: TC003 — used at runtime for manifest I/O
from typing import Any

from loguru import logger

from mergecraft.xrepo.linked_repos import (
    LinkedRepoAccessError,
    LinkedReposManifest,
    RunGrant,
    load_linked_repo_content,
    parse_manifest,
)
from mergecraft.xrepo.review import MANIFEST_REL, discover_linked_repo_roots, review_linked_repos

_AUTHORIZED_LINKED_REPOS_ENV = "MERGECRAFT_AUTHORIZED_LINKED_REPOS"


def operator_authorized_linked_repos() -> frozenset[str]:
    """Return the operator run grant from the environment (D9).

    PR-controlled ``linked-repos.yaml`` must not mint this set.
    """
    raw = os.environ.get(_AUTHORIZED_LINKED_REPOS_ENV, "")
    return frozenset(part.strip().lower() for part in raw.split(",") if part.strip())


def _intersect_manifest_grant(
    manifest: LinkedReposManifest, *, operator_grant: frozenset[str]
) -> frozenset[str]:
    grant = RunGrant(authorized_repos=frozenset(operator_grant))
    allowed: set[str] = set()
    for entry in manifest.repos:
        if grant.is_authorized(entry.name) or grant.is_authorized(entry.slug):
            allowed.add(entry.name.lower())
            allowed.add(entry.slug.lower())
    return frozenset(allowed)


def attach_linked_repo_review(
    repo_root: Path,
    *,
    authorized_repos: frozenset[str] | None = None,
) -> dict[str, Any] | None:
    """Parse the SHA-pinned manifest and return consumer-impact findings.

    Returns:
        A payload for ``checkout_pr`` when ``.mergecraft/linked-repos.yaml``
        exists, otherwise ``None``. Unauthorized linked repos raise
        :class:`LinkedRepoAccessError` and are omitted from findings.

    The operator grant (``authorized_repos``, typically from
    ``MERGECRAFT_AUTHORIZED_LINKED_REPOS``) is intersected with the manifest.
    An omitted grant is empty — the PR manifest cannot authorize itself.
    """
    manifest_path = repo_root / MANIFEST_REL
    if not manifest_path.is_file():
        return None
    manifest = parse_manifest(manifest_path)
    operator_grant = authorized_repos if authorized_repos is not None else frozenset()
    authorized = _intersect_manifest_grant(manifest, operator_grant=operator_grant)
    grant = RunGrant(authorized_repos=authorized)
    roots = discover_linked_repo_roots(repo_root=repo_root, manifest=manifest)
    for entry in manifest.repos:
        try:
            load_linked_repo_content(
                manifest=manifest,
                repo=entry.name,
                grant=grant,
                repo_roots=roots,
            )
        except (LinkedRepoAccessError, FileNotFoundError, OSError) as exc:
            logger.debug("linked-repo content skipped for {}: {}", entry.name, exc)
    review = review_linked_repos(repo_root=repo_root, authorized_repos=authorized)
    findings = [
        {
            "id": finding.finding_id,
            "consumer": finding.impact.repo,
            "producer": finding.impact.changed_contract.repo,
            "path": finding.impact.changed_contract.path,
            "kind": finding.impact.changed_contract.kind,
            "reason": finding.impact.reason,
        }
        for finding in review.findings
    ]
    return {
        "linkedRepoCount": len(manifest.repos),
        "linkedRepoFindings": findings,
    }


__all__ = ["attach_linked_repo_review", "operator_authorized_linked_repos"]
