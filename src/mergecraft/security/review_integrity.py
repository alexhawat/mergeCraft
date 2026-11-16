"""Post-run integrity helpers for read-only review sessions (MCB-06 / AP5).

Lane C's MCB-19 (AG2) reuses these helpers — import from here rather than
duplicating checkout/config fingerprint logic.

Exports:
    hash_tree: Fingerprint a checkout tree before agent execution.
    snapshot_tree: Digest plus per-path fingerprints in one walk.
    verify_tree_unchanged: Fail closed when the tree changed during review.
    TreeBaseline: The run's baseline, re-pinned across ``checkout_pr``.
    assert_checkout_read_boundary: Reject paths outside the checkout read allowlist.
    scan_local_sinks_for_secrets: Return the paths of local sinks holding secrets.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

_INTEGRITY_DIFF_PATH_LIMIT = 20

_SINK_SUFFIXES: frozenset[str] = frozenset({".log", ".txt", ".jsonl", ".ndjson"})
_SINK_NAMES: frozenset[str] = frozenset({"stdout", "stderr", "output"})


# Directory *names* pruned at any depth, not just at the checkout root. Workspace
# dependency prep (pnpm/yarn/npm) creates ``node_modules`` under every package —
# ``apps/api/node_modules``, ``packages/*/node_modules`` — and pnpm can drop its
# store in-tree as ``.pnpm-store``. Prep runs after the baseline, so hashing a
# nested tree failed every workspace review closed. A nested worktree or submodule
# keeps its own ``.git`` metadata directory for the same reason. Matched by
# directory name only: the walk prunes ``dirnames``, so a regular *file* that
# happens to share a name is still hashed.
#
# Python and tool caches are pruned the same way: ``__pycache__`` gets fresh
# ``.pyc`` files whenever a module is first (or newly) imported — in the checkout or
# in an in-tree virtualenv's site-packages — so a review of an editable install whose
# agent subprocess imports a lazily loaded module failed closed. The rest of a
# virtualenv stays hashed: gates that rewrite it run inside ``run_static_checks``,
# which re-pins the baseline, so any other write there is still caught.
_HASH_EXCLUDE_DIR_NAMES: frozenset[str] = frozenset(
    {
        ".git",
        "node_modules",
        ".pnpm-store",
        "__pycache__",
        # Linter and test-runner caches that ``run_static_checks`` writes when it runs
        # repo gates in the checkout mid-review.
        ".ruff_cache",
        ".mypy_cache",
        ".pytest_cache",
    }
)

# Exact checkout-relative paths excluded from the digest, matched for directories
# and files alike. Kept path-specific: ``evidence`` is a bare name here on purpose,
# because turning it into an any-depth directory name would also drop a nested
# directory of the same name that legitimately holds tracked files.
_HASH_EXCLUDE_REL_PATHS: frozenset[str] = frozenset(
    {
        ".mergecraft/prep-scratch",
        ".mergecraft/analyzer-scratch",
        # Analyzer runtime files mergeCraft itself writes into the checkout when a gate
        # runs unsandboxed (``analyzers/run.py`` SX-D13 output, ``analyzers/execution.py``
        # provisioning lock and its ``lockfile.py`` sidecar). A ``run_analyzers`` call made
        # mid-review lands them after the baseline, which failed every such review closed.
        # Exact paths: a sibling such as ``.mergecraft/config.yaml`` stays covered.
        ".mergecraft/analyzer-runs",
        ".mergecraft/analyzers.lock",
        ".mergecraft/analyzers.lock.lock",
        "evidence",
        ".opencode",
        "opencode-xdg-data",
        "opencode-xdg-config",
    }
)


def _is_excluded_rel_path(rel: str) -> bool:
    """Return whether a checkout-relative path is excluded from the digest."""
    return any(
        rel == excluded or rel.startswith(f"{excluded}/") for excluded in _HASH_EXCLUDE_REL_PATHS
    )


def _iter_tree_paths(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    paths: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        if rel_dir != "." and _is_excluded_rel_path(rel_dir):
            dirnames.clear()
            continue
        dirnames[:] = [
            name
            for name in dirnames
            if name not in _HASH_EXCLUDE_DIR_NAMES
            and not _is_excluded_rel_path(Path(dirpath).relative_to(root).joinpath(name).as_posix())
        ]
        for name in dirnames:
            path = Path(dirpath) / name
            if path.is_symlink():
                rel = path.relative_to(root).as_posix()
                if not _is_excluded_rel_path(rel):
                    paths.append(path)
        for name in filenames:
            path = Path(dirpath) / name
            rel = path.relative_to(root).as_posix()
            if _is_excluded_rel_path(rel):
                continue
            paths.append(path)
    return sorted(paths)


def _path_digest_payload(path: Path) -> bytes:
    if path.is_symlink():
        return b"symlink\0" + os.readlink(path).encode()
    return path.read_bytes()


@dataclass(frozen=True)
class TreeSnapshot:
    """Checkout tree digest and per-path fingerprints from one walk."""

    digest: str
    fingerprints: Mapping[str, str]


def snapshot_tree(root: Path) -> TreeSnapshot:
    """Return the tree digest and per-path fingerprints under ``root``."""
    resolved = root.resolve()
    fingerprints: dict[str, str] = {}
    digest = hashlib.sha256()
    for path in _iter_tree_paths(resolved):
        rel = path.relative_to(resolved).as_posix()
        payload = _path_digest_payload(path)
        fingerprints[rel] = hashlib.sha256(payload).hexdigest()
        digest.update(rel.encode())
        digest.update(b"\0")
        digest.update(payload)
        digest.update(b"\0")
    return TreeSnapshot(digest.hexdigest(), fingerprints)


def hash_tree(root: Path) -> str:
    """Return a stable digest of every file under ``root``."""
    return snapshot_tree(root).digest


def _diff_fingerprints(
    before: Mapping[str, str],
    after: Mapping[str, str],
) -> tuple[list[str], list[str], list[str]]:
    before_keys = set(before)
    after_keys = set(after)
    added = sorted(after_keys - before_keys)
    removed = sorted(before_keys - after_keys)
    modified = sorted(key for key in before_keys & after_keys if before[key] != after[key])
    return added, removed, modified


def _format_path_group(label: str, paths: Sequence[str], *, limit: int) -> str:
    if not paths:
        return ""
    if len(paths) <= limit:
        listing = ", ".join(paths)
    else:
        listing = ", ".join(paths[:limit]) + f" (+{len(paths) - limit} more)"
    return f"{label}: {listing}"


def format_tree_change_detail(
    before: Mapping[str, str],
    after: Mapping[str, str],
    *,
    limit: int = _INTEGRITY_DIFF_PATH_LIMIT,
) -> str:
    """Return added/removed/modified path groups; paths only, never file contents."""
    added, removed, modified = _diff_fingerprints(before, after)
    parts = [
        _format_path_group("added", added, limit=limit),
        _format_path_group("removed", removed, limit=limit),
        _format_path_group("modified", modified, limit=limit),
    ]
    return "\n".join(part for part in parts if part)


def checkout_integrity_failure_message(
    root: Path,
    before: Mapping[str, str],
    *,
    after: Mapping[str, str] | None = None,
    boundary: str | None = None,
) -> str:
    """Build the fail-closed integrity error for logs and ``AgentResult.error``."""
    resolved = root.resolve()
    if boundary:
        headline = (
            "checkout integrity failure: tree changed during read-only review "
            f"{boundary} ({resolved})"
        )
    else:
        headline = f"checkout integrity failure: tree changed during read-only review ({resolved})"
    if boundary is not None and not before:
        return headline
    if after is None:
        if boundary is not None:
            return headline
        current = snapshot_tree(resolved).fingerprints
    else:
        current = after
    detail = format_tree_change_detail(before, current, limit=_INTEGRITY_DIFF_PATH_LIMIT)
    if not detail:
        return headline
    return f"{headline}\n{detail}"


def verify_tree_unchanged(
    root: Path,
    before: TreeSnapshot | str,
    *,
    before_fingerprints: Mapping[str, str] | None = None,
) -> None:
    """Raise ``RuntimeError`` when the checkout changed during a read-only review."""
    fingerprints: Mapping[str, str] | None
    if isinstance(before, TreeSnapshot):
        before_digest = before.digest
        fingerprints = before.fingerprints
    else:
        before_digest = before
        fingerprints = before_fingerprints
    current_snap = snapshot_tree(root)
    if current_snap.digest == before_digest:
        return
    if fingerprints is None:
        msg = f"checkout integrity failure: tree changed during read-only review ({root.resolve()})"
        raise RuntimeError(msg)
    msg = checkout_integrity_failure_message(root, fingerprints, after=current_snap.fingerprints)
    raise RuntimeError(msg)


@dataclass
class TreeBaseline:
    """Read-only review baseline, kept on ``ToolState`` so mergeCraft's own tools can re-pin it.

    Two tools legitimately rewrite the tree, and each re-pins at its controlled
    boundary, after first checking nothing changed since the last pin:

    - ``checkout_pr``: the Action checks out the merge ref and the tool switches
      to the PR head, so every review of a branch behind its base failed closed.
    - ``run_static_checks`` on a trusted run: the repo's own gates run in place
      and write build output (``dist/``, generated docs), which a reviewer that
      calls the tool must not be blamed for. Untrusted gates run in the sandbox's
      write view and never touch the checkout.

    A change found at a boundary (ignored files survive ``git status`` gates)
    marks the baseline broken, so the re-pin cannot absorb it.
    """

    root: Path
    digest: str
    fingerprints: dict[str, str] = field(default_factory=dict)
    broken: bool = False
    broken_at: str = "checkout_pr"
    # Tree at the boundary where a pre-repin change was detected (before checkout/gates).
    broken_tree: dict[str, str] = field(default_factory=dict)

    @classmethod
    def capture(cls, root: Path) -> TreeBaseline:
        """Snapshot ``root`` for a read-only review integrity baseline."""
        snap = snapshot_tree(root)
        return cls(
            root=root.resolve(),
            digest=snap.digest,
            fingerprints=dict(snap.fingerprints),
        )

    def before_boundary(self, boundary: str) -> None:
        if not self.broken and hash_tree(self.root) != self.digest:
            current = snapshot_tree(self.root)
            self.broken = True
            self.broken_at = boundary
            self.broken_tree = dict(current.fingerprints)

    def after_boundary(self) -> None:
        if not self.broken:
            snap = snapshot_tree(self.root)
            self.digest = snap.digest
            self.fingerprints = dict(snap.fingerprints)

    def before_checkout(self) -> None:
        self.before_boundary("checkout_pr")

    def after_checkout(self) -> None:
        self.after_boundary()

    def verify(self) -> None:
        if self.broken:
            msg = checkout_integrity_failure_message(
                self.root,
                self.fingerprints,
                after=self.broken_tree,
                boundary=f"before {self.broken_at}",
            )
            raise RuntimeError(msg)
        verify_tree_unchanged(
            self.root,
            self.digest,
            before_fingerprints=self.fingerprints,
        )


def assert_checkout_read_boundary(checkout: Path, paths: Sequence[Path]) -> None:
    """Raise ``PermissionError`` when any path falls outside ``checkout``."""
    root = checkout.resolve()
    for raw in paths:
        candidate = raw.resolve()
        try:
            candidate.relative_to(root)
        except ValueError as err:
            msg = f"path {candidate} is outside checkout boundary {root}"
            raise PermissionError(msg) from err


def _is_sink_file(path: Path) -> bool:
    if path.suffix.lower() in _SINK_SUFFIXES:
        return True
    return path.name in _SINK_NAMES


def scan_local_sinks_for_secrets(
    search_root: Path | None,
    *,
    secrets: Sequence[str],
    explicit_paths: Sequence[Path] = (),
) -> list[Path]:
    """Return the *paths* of local sink files that contain any ``secrets`` literal.

    Returns matching paths only — **never** contents. Returning the contents
    would leak the credential the helper exists to catch the moment any caller
    logs or records the result (SX-D10). The caller is expected to name the
    path in its failure reason and delete the file, not to print the payload.

    ``search_root`` is walked recursively and filtered by the sink classifier
    (:func:`_is_sink_file`). ``explicit_paths`` names artifact sources the
    suffix/name classifier would miss — the evidence uploads are ``.json``
    packets, and ``.json`` is deliberately not a sink suffix — so each named
    file is scanned whether or not it looks like a sink.
    """
    hits: list[Path] = []
    if search_root is not None and search_root.is_dir():
        for path in sorted(search_root.rglob("*")):
            if path.is_file() and _is_sink_file(path):
                hits.append(path)
    for raw in explicit_paths:
        candidate = Path(raw)
        if candidate.is_file():
            hits.append(candidate)
    matches: list[Path] = []
    for path in dict.fromkeys(hits):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(secret and secret in text for secret in secrets):
            matches.append(path)
    return matches
