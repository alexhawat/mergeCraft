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
    """Return the operator run grant from the environment (D9, TB-D10).

    PR-controlled ``linked-repos.yaml`` must not mint this set. A grant must be
    an exact lowercase ``owner/name`` slug; a bare-name entry matches nothing
    and is warned once per entry (TB0 fork 4).
    """
    raw = os.environ.get(_AUTHORIZED_LINKED_REPOS_ENV, "")
    grant: set[str] = set()
    warned: set[str] = set()
    for part in raw.split(","):
        entry = part.strip().lower()
        if not entry:
            continue
        if "/" not in entry:
            if entry not in warned:
                warned.add(entry)
                logger.warning(
                    "ignoring bare linked-repo grant {!r}: grants must be exact owner/name slugs",
                    entry,
                )
            continue
        grant.add(entry)
    return frozenset(grant)


def _intersect_manifest_grant(
    manifest: LinkedReposManifest, *, operator_grant: frozenset[str]
) -> frozenset[str]:
    """Intersect the operator grant with the manifest, slugs only (TB-D10).

    A slug grant is never re-expanded to its bare name, and two manifest entries
    sharing a ``name`` are both refused: they would resolve to the same sibling
    directory, so the grant could not tell them apart.
    """
    grant = RunGrant(authorized_repos=frozenset(operator_grant))
    name_counts: dict[str, int] = {}
    for entry in manifest.repos:
        key = entry.name.lower()
        name_counts[key] = name_counts.get(key, 0) + 1
    allowed: set[str] = set()
    for entry in manifest.repos:
        if name_counts[entry.name.lower()] > 1:
            continue
        if grant.is_authorized(entry.slug):
            allowed.add(entry.slug.lower())
    return frozenset(allowed)


def attach_linked_repo_review(
    repo_root: Path,
    *,
    authorized_repos: frozenset[str] | None = None,
    base_manifest: LinkedReposManifest | None = None,
) -> dict[str, Any] | None:
    """Parse the SHA-pinned manifest and return consumer-impact findings.

    Returns:
        A payload for ``checkout_pr`` when ``.mergecraft/linked-repos.yaml``
        exists, otherwise ``None``. Unauthorized linked repos raise
        :class:`LinkedRepoAccessError` and are omitted from findings.

    The operator grant (``authorized_repos``, typically from
    ``MERGECRAFT_AUTHORIZED_LINKED_REPOS``) is intersected with the manifest.
    An omitted grant is empty — the PR manifest cannot authorize itself.

    ``base_manifest`` is the manifest as it existed at the PR base
    (``origin/<base>``). When it is supplied, findings report only contracts
    whose pin moved between the base and head manifests (TB-D11). An absent
    base manifest means no movement baseline: the review path reports no
    changed contract rather than a whole-index report. Every omitted entry —
    ungranted, missing sibling, pin mismatch, unreachable previous pin — is
    recorded in ``linkedRepoOmitted`` (TB-D12).
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
                repo=entry.slug,
                grant=grant,
                repo_roots=roots,
            )
        except (LinkedRepoAccessError, FileNotFoundError, OSError) as exc:
            logger.info("linked-repo content skipped for {}: {}", entry.slug, exc)
    review = review_linked_repos(
        repo_root=repo_root,
        authorized_repos=authorized,
        base_manifest=base_manifest if base_manifest is not None else LinkedReposManifest(repos=()),
    )
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
        "linkedRepoOmitted": [
            {"repo": omission.repo, "reason": omission.reason} for omission in review.omissions
        ],
    }


__all__ = ["attach_linked_repo_review", "operator_authorized_linked_repos"]
