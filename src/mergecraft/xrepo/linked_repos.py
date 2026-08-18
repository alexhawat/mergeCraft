"""Linked-repo manifest parsing, D9 access grant, and untrusted content fencing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path  # noqa: TC003 — used at runtime for manifest I/O

import yaml

from mergecraft.utils.bounded_text import read_bounded_text, resolve_path_under_root
from mergecraft.utils.fence import Fence, render_untrusted


class LinkedRepoAccessError(PermissionError):
    """Raised when a run attempts to read a linked repo outside its grant (D9)."""


@dataclass(frozen=True, slots=True)
class LinkedRepoEntry:
    """One linked repository pinned at an explicit commit."""

    owner: str
    name: str
    commit: str

    @property
    def slug(self) -> str:
        """Return ``owner/name`` repo slug."""
        return f"{self.owner}/{self.name}"


@dataclass(frozen=True, slots=True)
class LinkedReposManifest:
    """Parsed linked-repo manifest declaring repos at pinned commits."""

    repos: tuple[LinkedRepoEntry, ...]

    def entry_for(self, repo: str) -> LinkedRepoEntry | None:
        """Resolve a repo by bare name or ``owner/name`` slug."""
        normalized = repo.strip().lower()
        for entry in self.repos:
            if entry.name.lower() == normalized or entry.slug.lower() == normalized:
                return entry
        return None


@dataclass(frozen=True, slots=True)
class RunGrant:
    """Authorized linked-repo names for this run (D9 access boundary)."""

    authorized_repos: frozenset[str]

    def is_authorized(self, repo: str) -> bool:
        """Return True when ``repo`` is in the grant set (bare name or slug tail)."""
        normalized = repo.strip().lower()
        tail = normalized.rsplit("/", 1)[-1]
        return normalized in self.authorized_repos or tail in self.authorized_repos


def parse_manifest(path: Path) -> LinkedReposManifest:
    """Parse ``.mergecraft/linked-repos.yaml`` into a typed manifest."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = f"linked-repo manifest must be a mapping: {path}"
        raise ValueError(msg)
    repos_raw = raw.get("repos", [])
    if not isinstance(repos_raw, list):
        msg = f"linked-repo manifest 'repos' must be a list: {path}"
        raise ValueError(msg)
    entries: list[LinkedRepoEntry] = []
    for item in repos_raw:
        if not isinstance(item, dict):
            continue
        owner = str(item.get("owner", "")).strip()
        name = str(item.get("name", "")).strip()
        commit = str(item.get("commit", "")).strip()
        if not owner or not name or not commit:
            msg = f"linked-repo entry requires owner, name, and commit: {item!r}"
            raise ValueError(msg)
        entries.append(LinkedRepoEntry(owner=owner, name=name, commit=commit))
    return LinkedReposManifest(repos=tuple(entries))


def load_linked_repo_content(
    *,
    manifest: LinkedReposManifest,
    repo: str,
    grant: RunGrant,
    repo_roots: dict[str, Path] | None = None,
    relative_path: str = "README.md",
) -> str:
    """Load content from a linked repo when authorized for this run (D9).

    Raises:
        LinkedRepoAccessError: When ``repo`` is not in ``grant.authorized_repos``.
        FileNotFoundError: When the repo root or requested file is missing.
    """
    if not grant.is_authorized(repo):
        msg = f'repo "{repo}" is not authorized for this run'
        raise LinkedRepoAccessError(msg)
    entry = manifest.entry_for(repo)
    if entry is None:
        msg = f'repo "{repo}" is not declared in the linked-repo manifest'
        raise FileNotFoundError(msg)
    if repo_roots is None:
        return ""
    root_key = entry.name if entry.name in repo_roots else repo.rsplit("/", 1)[-1]
    root = repo_roots.get(root_key)
    if root is None:
        msg = f"no checkout root for linked repo {repo!r}"
        raise FileNotFoundError(msg)
    target = resolve_path_under_root(root, relative_path)
    if not target.is_file():
        msg = f"linked repo content not found: {target}"
        raise FileNotFoundError(msg)
    content = read_bounded_text(target)
    if content is None:
        msg = f"linked repo content unreadable: {target}"
        raise FileNotFoundError(msg)
    return content


def render_linked_repo_context(
    *,
    content: str,
    repo: str,
    commit: str,
    author: str,
) -> str:
    """Render linked-repo content through the W4 fence as untrusted data."""
    fence = Fence()
    cited = f"### `{repo}` @ {commit}\n\n{content.strip()}"
    return render_untrusted(
        cited,
        author=author,
        tier="untrusted",
        label=f"linked_repo_content:{repo}@{commit}",
        nonce=fence.nonce,
    )


__all__ = [
    "LinkedRepoAccessError",
    "LinkedRepoEntry",
    "LinkedReposManifest",
    "RunGrant",
    "load_linked_repo_content",
    "parse_manifest",
    "render_linked_repo_context",
]
