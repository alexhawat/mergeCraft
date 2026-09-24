"""Review-path wiring for SHA-pinned linked repos and contract blast radius (#353).

Output-only (D13): never writes into the reviewed tree.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from loguru import logger

from mergecraft.context.repo_paths import git_blob_sha
from mergecraft.mcp.git_guards import reject_if_leading_dash
from mergecraft.utils.git_hardening import git_argv
from mergecraft.xrepo.blast_radius import (
    ChangedContract,
    CrossRepoImpact,
    resolve_cross_repo_dependents,
)
from mergecraft.xrepo.citations import validate_pinned_sha
from mergecraft.xrepo.contract_index import (
    ContractIndex,
    ContractSurface,
    index_contracts_at_commit,
)
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
class LinkedRepoOmission:
    """One linked-repo entry that was not reviewed, and why (TB-D12)."""

    repo: str
    reason: str


@dataclass(frozen=True, slots=True)
class XrepoReview:
    """Linked-repo review result: SHA-pinned manifest plus consumer findings."""

    manifest: LinkedReposManifest
    findings: tuple[XrepoFinding, ...]
    producer: LinkedRepoEntry | None
    omissions: tuple[LinkedRepoOmission, ...] = ()


def _is_safe_sibling_name(name: str) -> bool:
    """Reject anything that is not a single directory component under the sibling parent."""
    if not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name:
        return False
    path = Path(name)
    if path.is_absolute() or path.anchor:
        return False
    return path.parts == (name,)


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
    return RunGrant(authorized_repos=frozenset(entry.slug.lower() for entry in manifest.repos))


def _authorized_roots(
    *,
    roots: dict[str, Path],
    grant: RunGrant,
    manifest: LinkedReposManifest,
) -> dict[str, Path]:
    """Keep sibling roots whose owning entry's slug is granted (TB-D10).

    Two manifest entries sharing a ``name`` resolve to the same sibling
    directory, so neither is authorized: the grant cannot distinguish them.
    """
    name_counts: dict[str, int] = {}
    for entry in manifest.repos:
        key = entry.name.lower()
        name_counts[key] = name_counts.get(key, 0) + 1
    authorized: dict[str, Path] = {}
    for entry in manifest.repos:
        if name_counts[entry.name.lower()] > 1:
            continue
        if not grant.is_authorized(entry.slug):
            continue
        path = roots.get(entry.name)
        if path is not None:
            authorized[entry.name] = path
    return authorized


def _indexed_surfaces(index: ContractIndex) -> tuple[ContractSurface, ...]:
    return (*index.openapi, *index.graphql, *index.protobuf, *index.exports)


def _changed_from_index(*, repo: str, commit: str, index: ContractIndex) -> list[ChangedContract]:
    return [
        ChangedContract(
            repo=repo,
            commit=commit,
            path=surface.path,
            kind=surface.kind or "contract",
            operation_id=surface.symbol,
        )
        for surface in _indexed_surfaces(index)
    ]


def _changed_between_pins(
    *,
    repo_root: Path,
    repo: str,
    base_commit: str,
    head_commit: str,
    base_index: ContractIndex,
    head_index: ContractIndex,
) -> list[ChangedContract]:
    """Return head surfaces whose path differs between the two pinned commits (TB-D11).

    A surface is changed when its path is new at the head pin or its blob differs
    between the pins. Surfaces whose file is byte-identical at both pins are not
    reported: the PR did not change them.
    """
    base_paths = {surface.path for surface in _indexed_surfaces(base_index)}
    changed: list[ChangedContract] = []
    for surface in _indexed_surfaces(head_index):
        if surface.path in base_paths and git_blob_sha(
            repo_root, base_commit, surface.path
        ) == git_blob_sha(repo_root, head_commit, surface.path):
            continue
        changed.append(
            ChangedContract(
                repo=repo,
                commit=head_commit,
                path=surface.path,
                kind=surface.kind or "contract",
                operation_id=surface.symbol,
            )
        )
    return changed


def _rev_parse_commit(repo_root: Path, rev: str) -> str:
    stripped = rev.strip()
    reject_if_leading_dash(stripped, "rev")
    if stripped != "HEAD":
        validate_pinned_sha(stripped)
    completed = subprocess.run(
        git_argv(
            [
                "-C",
                str(repo_root),
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{stripped}^{{commit}}",
            ]
        ),
        capture_output=True,
        check=False,
        text=True,
    )
    sha = completed.stdout.strip()
    if completed.returncode != 0 or not sha:
        msg = f"could not resolve {rev!r} in {repo_root}"
        raise ValueError(msg)
    return sha


def _require_head_matches_pin(repo_root: Path, commit_sha: str) -> None:
    """Fail closed when the sibling checkout is not the pinned commit object."""
    pin = commit_sha.strip()
    if not pin:
        msg = f"empty pinned commit for {repo_root}"
        raise ValueError(msg)
    head = _rev_parse_commit(repo_root, "HEAD")
    resolved_pin = _rev_parse_commit(repo_root, pin)
    if head != resolved_pin:
        msg = f"linked repo HEAD {head} does not match pinned {pin}"
        raise ValueError(msg)
    dirty = subprocess.run(
        git_argv(["-C", str(repo_root), "status", "--porcelain", "--untracked-files=all"]),
        capture_output=True,
        check=False,
        text=True,
    )
    if dirty.returncode != 0 or dirty.stdout.strip():
        msg = f"linked repo worktree is dirty at {repo_root}"
        raise ValueError(msg)


def _base_entry_for(base_manifest: LinkedReposManifest | None, slug: str) -> LinkedRepoEntry | None:
    """Find the base-manifest entry for an exact ``owner/name`` slug."""
    if base_manifest is None:
        return None
    target = slug.strip().lower()
    for entry in base_manifest.repos:
        if entry.slug.lower() == target:
            return entry
    return None


def _index_at(
    *,
    root: Path,
    name: str,
    commit: str,
    cache: dict[tuple[str, str], ContractIndex],
) -> ContractIndex:
    key = (name, commit)
    if key not in cache:
        cache[key] = index_contracts_at_commit(repo_root=root, commit_sha=commit)
    return cache[key]


def review_linked_repos(
    *,
    repo_root: Path,
    producer: str | None = None,
    authorized_repos: frozenset[str] | None = None,
    base_manifest: LinkedReposManifest | None = None,
) -> XrepoReview:
    """Parse the SHA-pinned manifest, index producer contracts, resolve consumers.

    Args:
        repo_root: Primary checkout that owns ``.mergecraft/linked-repos.yaml``.
        producer: Optional ``owner/name`` or bare name to treat as the producer.
            An explicit producer keeps whole-index semantics (an operator
            assertion, not a PR claim).
        authorized_repos: Optional grant set; defaults to every manifest entry.
        base_manifest: Optional manifest as it existed at the PR base. When
            supplied, the change set is pin movement (TB-D11): only granted
            entries whose pin moved contribute, and only surfaces whose path
            differs between the two pins. When omitted, every indexed surface is
            reported (the legacy whole-index behaviour).

    Returns:
        An ``XrepoReview`` with ``XR-NNN`` findings (empty when no manifest) and
        one :class:`LinkedRepoOmission` per skipped entry.
    """
    manifest_path = repo_root / MANIFEST_REL
    if not manifest_path.is_file():
        return XrepoReview(manifest=LinkedReposManifest(repos=()), findings=(), producer=None)
    manifest = parse_manifest(manifest_path)
    grant = _grant_for_manifest(manifest, authorized_repos=authorized_repos)
    all_roots = discover_linked_repo_roots(repo_root=repo_root, manifest=manifest)
    roots = _authorized_roots(roots=all_roots, grant=grant, manifest=manifest)

    omissions: list[LinkedRepoOmission] = []
    for entry in manifest.repos:
        if not grant.is_authorized(entry.slug):
            omissions.append(
                LinkedRepoOmission(repo=entry.slug, reason="not authorized for this run")
            )
        elif all_roots.get(entry.name) is None:
            omissions.append(
                LinkedRepoOmission(repo=entry.slug, reason="sibling checkout not found")
            )

    pinned_roots: dict[str, Path] = {}
    for entry in manifest.repos:
        root = roots.get(entry.name)
        if root is None:
            continue
        try:
            _require_head_matches_pin(root, entry.commit)
        except ValueError as exc:
            omissions.append(LinkedRepoOmission(repo=entry.slug, reason=f"pin mismatch: {exc}"))
            continue
        pinned_roots[entry.name] = root
    roots = pinned_roots

    producer_entry = manifest.entry_for(producer) if producer else None
    producers = (producer_entry,) if producer_entry is not None else manifest.repos
    movement = producer is None and base_manifest is not None

    index_cache: dict[tuple[str, str], ContractIndex] = {}
    changed: list[ChangedContract] = []
    for entry in producers:
        root = roots.get(entry.name)
        if root is None:
            continue
        if movement:
            base_entry = _base_entry_for(base_manifest, entry.slug)
            if base_entry is None or base_entry.commit.lower() == entry.commit.lower():
                continue
            try:
                _rev_parse_commit(root, base_entry.commit)
            except ValueError:
                omissions.append(
                    LinkedRepoOmission(
                        repo=entry.slug,
                        reason=f"previous pin unreachable: {base_entry.commit}",
                    )
                )
                continue
            head_index = _index_at(
                root=root, name=entry.name, commit=entry.commit, cache=index_cache
            )
            base_index = _index_at(
                root=root, name=entry.name, commit=base_entry.commit, cache=index_cache
            )
            changed.extend(
                _changed_between_pins(
                    repo_root=root,
                    repo=entry.slug,
                    base_commit=base_entry.commit,
                    head_commit=entry.commit,
                    base_index=base_index,
                    head_index=head_index,
                )
            )
        else:
            index = _index_at(root=root, name=entry.name, commit=entry.commit, cache=index_cache)
            changed.extend(_changed_from_index(repo=entry.slug, commit=entry.commit, index=index))

    for omission in omissions:
        logger.info("linked-repo omitted {}: {}", omission.repo, omission.reason)

    impacts = resolve_cross_repo_dependents(
        changed_contracts=changed,
        manifest=manifest,
        repo_roots=roots,
        at_pinned_commit=True,
    )
    findings = tuple(
        XrepoFinding(finding_id=f"XR-{index:03d}", impact=impact)
        for index, impact in enumerate(impacts, start=1)
    )
    return XrepoReview(
        manifest=manifest,
        findings=findings,
        producer=producer_entry,
        omissions=tuple(omissions),
    )


__all__ = [
    "MANIFEST_REL",
    "LinkedRepoOmission",
    "XrepoFinding",
    "XrepoReview",
    "discover_linked_repo_roots",
    "review_linked_repos",
]
