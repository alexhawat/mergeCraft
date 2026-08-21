"""Review-path wiring for SHA-pinned linked repos and contract blast radius (#353).

Output-only (D13): never writes into the reviewed tree.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from mergecraft.xrepo.blast_radius import (
    ChangedContract,
    CrossRepoImpact,
    resolve_cross_repo_dependents,
)
from mergecraft.xrepo.contract_index import ContractIndex, index_contracts
from mergecraft.xrepo.linked_repos import (
    LinkedRepoEntry,
    LinkedReposManifest,
    RunGrant,
    parse_manifest,
)

MANIFEST_REL = Path(".mergecraft") / "linked-repos.yaml"


@dataclass(frozen=True, slots=True)
class XrepoFinding:
    """One consumer impact from a producer contract change."""

    finding_id: str
    impact: CrossRepoImpact


@dataclass(frozen=True, slots=True)
class XrepoReview:
    """Linked-repo review result: SHA-pinned manifest plus consumer findings."""

    manifest: LinkedReposManifest
    findings: tuple[XrepoFinding, ...]
    producer: LinkedRepoEntry | None


def _is_safe_sibling_name(name: str) -> bool:
    """Reject absolute paths, separators, and ``..`` in a manifest directory name."""
    if not name or name in {".", ".."}:
        return False
    path = Path(name)
    if path.is_absolute() or path.anchor:
        return False
    return all(
        part not in {"", ".", ".."} and "/" not in part and "\\" not in part for part in path.parts
    )


def discover_linked_repo_roots(
    *,
    repo_root: Path,
    manifest: LinkedReposManifest,
) -> dict[str, Path]:
    """Resolve sibling checkouts next to the primary repo by linked-repo name."""
    parent = repo_root.parent.resolve()
    roots: dict[str, Path] = {}
    for entry in manifest.repos:
        if not _is_safe_sibling_name(entry.name):
            continue
        candidate = (parent / entry.name).resolve()
        if not candidate.is_dir():
            continue
        if not candidate.is_relative_to(parent) or candidate == parent:
            continue
        roots[entry.name] = candidate
    return roots


def _grant_for_manifest(
    manifest: LinkedReposManifest,
    *,
    authorized_repos: frozenset[str] | None,
) -> RunGrant:
    if authorized_repos is not None:
        return RunGrant(authorized_repos=authorized_repos)
    names: set[str] = set()
    for entry in manifest.repos:
        names.add(entry.name.lower())
        names.add(entry.slug.lower())
    return RunGrant(authorized_repos=frozenset(names))


def _authorized_roots(
    *,
    roots: dict[str, Path],
    grant: RunGrant,
) -> dict[str, Path]:
    return {name: path for name, path in roots.items() if grant.is_authorized(name)}


def _changed_from_index(*, repo: str, commit: str, index: ContractIndex) -> list[ChangedContract]:
    surfaces = (*index.openapi, *index.graphql, *index.protobuf, *index.exports)
    return [
        ChangedContract(
            repo=repo,
            commit=commit,
            path=surface.path,
            kind=surface.kind or "contract",
            operation_id=surface.symbol,
        )
        for surface in surfaces
    ]


def _require_head_matches_pin(repo_root: Path, commit_sha: str) -> None:
    """Fail closed when the sibling checkout HEAD is not the pinned SHA."""
    completed = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        capture_output=True,
        check=False,
        text=True,
    )
    head = completed.stdout.strip()
    pin = commit_sha.strip()
    if completed.returncode != 0 or not head:
        msg = f"could not read HEAD in {repo_root}"
        raise ValueError(msg)
    if head != pin and not head.startswith(pin) and not pin.startswith(head):
        msg = f"linked repo HEAD {head} does not match pinned {pin}"
        raise ValueError(msg)
    dirty = subprocess.run(
        ["git", "-C", str(repo_root), "status", "--porcelain"],
        capture_output=True,
        check=False,
        text=True,
    )
    if dirty.returncode != 0 or dirty.stdout.strip():
        msg = f"linked repo worktree is dirty at {repo_root}"
        raise ValueError(msg)


def review_linked_repos(
    *,
    repo_root: Path,
    producer: str | None = None,
    authorized_repos: frozenset[str] | None = None,
) -> XrepoReview:
    """Parse the SHA-pinned manifest, index producer contracts, resolve consumers.

    Args:
        repo_root: Primary checkout that owns ``.mergecraft/linked-repos.yaml``.
        producer: Optional ``owner/name`` or bare name to treat as the producer.
        authorized_repos: Optional grant set; defaults to every manifest entry.

    Returns:
        An ``XrepoReview`` with ``XR-NNN`` findings (empty when no manifest).
    """
    manifest_path = repo_root / MANIFEST_REL
    if not manifest_path.is_file():
        return XrepoReview(manifest=LinkedReposManifest(repos=()), findings=(), producer=None)
    manifest = parse_manifest(manifest_path)
    grant = _grant_for_manifest(manifest, authorized_repos=authorized_repos)
    roots = _authorized_roots(
        roots=discover_linked_repo_roots(repo_root=repo_root, manifest=manifest),
        grant=grant,
    )
    pinned_roots: dict[str, Path] = {}
    for entry in manifest.repos:
        root = roots.get(entry.name)
        if root is None:
            continue
        try:
            _require_head_matches_pin(root, entry.commit)
        except ValueError:
            continue
        pinned_roots[entry.name] = root
    roots = pinned_roots

    producer_entry = manifest.entry_for(producer) if producer else None
    producers = (producer_entry,) if producer_entry is not None else manifest.repos

    index_cache: dict[tuple[str, str], ContractIndex] = {}
    changed: list[ChangedContract] = []
    for entry in producers:
        root = roots.get(entry.name)
        if root is None:
            continue
        cache_key = (entry.name, entry.commit)
        if cache_key not in index_cache:
            index_cache[cache_key] = index_contracts(repo_root=root, commit_sha=entry.commit)
        changed.extend(
            _changed_from_index(repo=entry.slug, commit=entry.commit, index=index_cache[cache_key])
        )

    impacts = resolve_cross_repo_dependents(
        changed_contracts=changed,
        manifest=manifest,
        repo_roots=roots,
    )
    findings = tuple(
        XrepoFinding(finding_id=f"XR-{index:03d}", impact=impact)
        for index, impact in enumerate(impacts, start=1)
    )
    return XrepoReview(manifest=manifest, findings=findings, producer=producer_entry)


__all__ = [
    "MANIFEST_REL",
    "XrepoFinding",
    "XrepoReview",
    "discover_linked_repo_roots",
    "review_linked_repos",
]
