"""Cross-repo blast radius — contract changes to dependent repositories."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for consumer traversal

from mergecraft.context.repo_paths import git_ls_tree_paths, git_show_text
from mergecraft.utils.bounded_text import (
    MAX_CONSUMER_HAYSTACK_BYTES,
    iter_indexable_files,
    read_bounded_text,
)
from mergecraft.xrepo.linked_repos import (
    LinkedReposManifest,  # noqa: TC001 — runtime manifest access
)


@dataclass(frozen=True, slots=True)
class ChangedContract:
    """A contract surface change in a linked repository."""

    repo: str
    commit: str
    path: str
    kind: str
    operation_id: str | None = None


@dataclass(frozen=True, slots=True)
class CrossRepoImpact:
    """A dependent repository affected by a contract change."""

    repo: str
    commit: str
    reason: str
    changed_contract: ChangedContract


def _path_stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    if "." in name:
        return name.rsplit(".", 1)[0]
    return name


def _operation_tokens(operation_id: str) -> set[str]:
    snake = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", operation_id).lower()
    tokens = {token for token in re.split(r"[_\s]+", snake) if token}
    if snake.endswith("s") and len(snake) > 1:
        tokens.add(snake[:-1])
    return tokens


def _haystack_from_worktree(consumer_root: Path) -> str:
    haystack_parts: list[str] = []
    total_bytes = 0
    for path in iter_indexable_files(consumer_root):
        text = read_bounded_text(path)
        if text is None:
            continue
        encoded = text.encode("utf-8", errors="replace")
        if total_bytes + len(encoded) > MAX_CONSUMER_HAYSTACK_BYTES:
            break
        haystack_parts.append(text)
        total_bytes += len(encoded)
    return "\n".join(haystack_parts).lower()


def _haystack_from_commit(consumer_root: Path, commit_sha: str) -> str:
    haystack_parts: list[str] = []
    total_bytes = 0
    for rel in git_ls_tree_paths(consumer_root, commit_sha):
        text = git_show_text(consumer_root, commit_sha, rel)
        if text is None:
            continue
        encoded = text.encode("utf-8", errors="replace")
        if total_bytes + len(encoded) > MAX_CONSUMER_HAYSTACK_BYTES:
            break
        haystack_parts.append(text)
        total_bytes += len(encoded)
    return "\n".join(haystack_parts).lower()


def _consumer_refs_contract(
    *,
    consumer_root: Path,
    contract_repo: str,
    contract_commit: str,
    contract_path: str,
    operation_id: str | None,
    consumer_commit: str | None = None,
) -> str | None:
    """Return a human reason when the consumer references the contract."""
    haystack = (
        _haystack_from_commit(consumer_root, consumer_commit)
        if consumer_commit
        else _haystack_from_worktree(consumer_root)
    )
    repo_tail = contract_repo.rsplit("/", 1)[-1].lower()
    if contract_commit.lower() not in haystack and repo_tail not in haystack:
        return None

    path_norm = contract_path.lower().replace("\\", "/")
    path_stem = _path_stem(path_norm)
    contract_markers = {path_norm, path_stem}
    if operation_id:
        contract_markers.add(operation_id.lower())
        contract_markers.update(_operation_tokens(operation_id))
    if not any(marker and marker in haystack for marker in contract_markers):
        return None

    return f"references {contract_repo}@{contract_commit} {contract_path}" + (
        f" ({operation_id})" if operation_id else ""
    )


def resolve_cross_repo_dependents(
    *,
    changed_contracts: list[ChangedContract],
    manifest: LinkedReposManifest,
    repo_roots: dict[str, Path],
    at_pinned_commit: bool = False,
) -> list[CrossRepoImpact]:
    """Resolve linked repos that depend on changed contract surfaces."""
    impacts: list[CrossRepoImpact] = []
    for changed in changed_contracts:
        source_tail = changed.repo.rsplit("/", 1)[-1]
        for entry in manifest.repos:
            if entry.name == source_tail or entry.slug == changed.repo:
                continue
            consumer_root = repo_roots.get(entry.name)
            if consumer_root is None:
                continue
            reason = _consumer_refs_contract(
                consumer_root=consumer_root,
                contract_repo=changed.repo,
                contract_commit=changed.commit,
                contract_path=changed.path,
                operation_id=changed.operation_id,
                consumer_commit=entry.commit if at_pinned_commit else None,
            )
            if reason is None:
                continue
            impacts.append(
                CrossRepoImpact(
                    repo=entry.slug,
                    commit=entry.commit,
                    reason=reason,
                    changed_contract=changed,
                )
            )
    return impacts


__all__ = ["ChangedContract", "CrossRepoImpact", "resolve_cross_repo_dependents"]
