"""Attach SHA-pinned linked-repo review to the ordinary checkout path (#353).

Output-only: never writes into the reviewed tree.
"""

from __future__ import annotations

from pathlib import Path  # noqa: TC003 — used at runtime for manifest I/O
from typing import Any

from loguru import logger

from mergecraft.xrepo.linked_repos import (
    LinkedRepoAccessError,
    RunGrant,
    load_linked_repo_content,
    parse_manifest,
)
from mergecraft.xrepo.review import MANIFEST_REL, discover_linked_repo_roots, review_linked_repos


def attach_linked_repo_review(repo_root: Path) -> dict[str, Any] | None:
    """Parse the SHA-pinned manifest and return consumer-impact findings.

    Returns:
        A payload for ``checkout_pr`` when ``.mergecraft/linked-repos.yaml``
        exists, otherwise ``None``. Unauthorized linked repos raise
        :class:`LinkedRepoAccessError` and are omitted from findings.
    """
    manifest_path = repo_root / MANIFEST_REL
    if not manifest_path.is_file():
        return None
    manifest = parse_manifest(manifest_path)
    authorized = frozenset(
        token.lower() for entry in manifest.repos for token in (entry.name, entry.slug)
    )
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


__all__ = ["attach_linked_repo_review"]
