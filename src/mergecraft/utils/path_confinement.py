"""Confine untrusted repository paths to a checkout root (MCB-20, D13).

Also the single credential-path denylist and tool-path confinement rule the
MCP ``git``, ``shell`` and ``upload_file`` tools share: every check resolves
the path (following symlinks, against the directory the tool runs in) before
matching, so two spellings of one file get one answer.
"""

from __future__ import annotations

import glob
import os
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence


class ToolPathError(ValueError):
    """Raised when a tool path operand is refused."""


def _denied_relative_paths() -> tuple[str, ...]:
    from mergecraft.utils.git_setup import reviewer_denied_relative_paths

    return reviewer_denied_relative_paths()


def _askpass_root(tmpdir: str) -> Path:
    from mergecraft.utils.git_setup import reviewer_askpass_credentials_dir

    return reviewer_askpass_credentials_dir(tmpdir)


def resolve_tool_path(value: str, *, base: str) -> Path | None:
    """Resolve *value* the way a tool running in *base* would, or ``None``.

    A relative value is joined to *base*; symlinks that exist are followed. A
    NUL byte or an unresolvable path yields ``None``.
    """
    if "\x00" in value:
        return None
    candidate = Path(os.path.expanduser(value)) if value.startswith("~") else Path(value)
    try:
        if candidate.is_absolute():
            return candidate.resolve()
        return (Path(base) / candidate).resolve()
    except (OSError, RuntimeError):  # fmt: skip
        return None


def _casefold_parts(path: Path) -> tuple[str, ...]:
    return tuple(part.casefold() for part in path.parts)


def _tail_matches(resolved: Path, denied_rel: str) -> bool:
    denied = _casefold_parts(Path(denied_rel))
    parts = _casefold_parts(resolved)
    return len(parts) >= len(denied) and parts[-len(denied) :] == denied


def _is_under(resolved: Path, root: Path) -> bool:
    parts, root_parts = _casefold_parts(resolved), _casefold_parts(root)
    return parts[: len(root_parts)] == root_parts


def _same_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


def is_denied_credential_path(
    path: str,
    *,
    cwd: str,
    tmpdir: str = "",
    checkout_roots: Iterable[str] = (),
) -> bool:
    """Whether *path* names git credential material or the askpass tree.

    The path is resolved against *cwd* first. It is denied when its resolved
    location ends in a denied checkout-relative path (``.git/config``,
    ``.git/credentials``; compared case-insensitively so a case-insensitive
    filesystem gives no second spelling), is the same file as one of those
    under *cwd* or any of *checkout_roots*, or sits inside the askpass
    credentials tree under *tmpdir*.
    """
    resolved = resolve_tool_path(path, base=cwd)
    if resolved is None:
        return False
    denied_rel = _denied_relative_paths()
    if any(_tail_matches(resolved, rel) for rel in denied_rel):
        return True
    for root in (cwd, *checkout_roots):
        if not root:
            continue
        for rel in denied_rel:
            if _same_file(resolved, Path(root) / rel):
                return True
    if tmpdir:
        try:
            askpass = _askpass_root(tmpdir).resolve()
        except OSError:
            return False
        if _is_under(resolved, askpass):
            return True
    return False


_GLOB_CHARS = frozenset("*?[")


def expand_operand(operand: str, *, base: str) -> list[str]:
    """Return *operand* plus whatever a shell glob in it matches under *base*."""
    if not _GLOB_CHARS.intersection(operand):
        return [operand]
    pattern = operand if os.path.isabs(operand) else os.path.join(base, operand)
    try:
        matches = glob.glob(pattern, include_hidden=True)
    except (OSError, ValueError):  # fmt: skip
        matches = []
    return [operand, *matches]


def confine_tool_path(
    value: str,
    *,
    base: str,
    tmpdir: str = "",
    checkout_roots: Sequence[str] = (),
    extra_roots: Sequence[str] = (),
) -> Path:
    """Resolve *value*, refuse credential material, and confine it to the workspace.

    The one rule for a tool that reads a caller-named file: resolve against
    *base*, refuse anything :func:`is_denied_credential_path` denies, then
    require the result to sit under an allowed workspace root (or one of
    *extra_roots*, such as the session tmpdir).

    Raises:
        ToolPathError: when the path is credential material or out of bounds.
    """
    from mergecraft.utils.workspace import WorkspacePathError, confine_to_workspace

    if is_denied_credential_path(value, cwd=base, tmpdir=tmpdir, checkout_roots=checkout_roots):
        name = Path(value).name or value
        msg = f"'{name}' is credential material and is not available to tools"
        raise ToolPathError(msg)
    try:
        return confine_to_workspace(value, base=base, extra_roots=extra_roots)
    except WorkspacePathError as exc:
        raise ToolPathError(str(exc)) from exc


def checkout_identity_paths(roots: Iterable[str]) -> tuple[set[Path], set[Path]]:
    """Return the resolved work-tree roots and git dirs of registered checkouts.

    A root's git dir is its ``.git`` entry and, when git can resolve one, the
    directory ``rev-parse --absolute-git-dir`` names (a linked worktree keeps
    it outside the tree).
    """
    from mergecraft.utils.git_hardening import absolute_git_dir

    work_trees: set[Path] = set()
    git_dirs: set[Path] = set()
    root_list = [root for root in roots if root]
    for root in root_list:
        with suppress(OSError):
            resolved = Path(root).resolve()
            work_trees.add(resolved)
            git_dirs.add((resolved / ".git").resolve())
        found = absolute_git_dir(root, safe_directories=root_list)
        if found is not None:
            git_dirs.add(found)
    return work_trees, git_dirs


def resolve_confined_path(
    root: str | Path,
    untrusted_path: str,
    *,
    changed_paths: frozenset[str] | None = None,
) -> str:
    """Resolve ``untrusted_path`` inside ``root`` or raise ``ValueError``.

    Rejects absolute paths, traversal, NUL bytes, prefix collisions
    (``/repo`` vs ``/repo2``), symlinks that resolve outside ``root``, and
    (when provided) paths outside ``changed_paths``.
    """
    if "\x00" in untrusted_path:
        msg = "path contains a NUL byte"
        raise ValueError(msg)
    if Path(untrusted_path).is_absolute():
        msg = "absolute paths are not allowed"
        raise ValueError(msg)

    repo_root = Path(root).resolve()
    candidate = (repo_root / untrusted_path).resolve()
    if not _is_under_root(candidate, repo_root):
        msg = f"path {untrusted_path!r} escapes the repository root"
        raise ValueError(msg)
    if not candidate.is_file():
        msg = f"path {untrusted_path!r} is not a file in the checkout"
        raise ValueError(msg)

    relative = candidate.relative_to(repo_root).as_posix()
    if changed_paths is not None and relative not in changed_paths:
        msg = f"path {untrusted_path!r} is not in the changed-path set"
        raise ValueError(msg)
    return str(candidate)


def resolved_within_root(path: Path, root: Path) -> bool:
    """True when ``path``'s resolved location stays inside the resolved ``root``.

    The one reference-resolver rule shared by instruction discovery and the
    agent-security scanner: resolve (following every symlink), then require the
    result to sit under ``root``. A filename is not a location — a symlink whose
    target lives outside the repository is not an in-repo file, however its link
    is named. ``root`` must already be resolved. Any resolution failure counts as
    an escape.
    """
    try:
        path.resolve().relative_to(root)
    except (OSError, ValueError):
        return False
    return True


def _is_under_root(candidate: Path, repo_root: Path) -> bool:
    try:
        candidate.relative_to(repo_root)
    except ValueError:
        return False
    return True


__all__ = [
    "ToolPathError",
    "checkout_identity_paths",
    "confine_tool_path",
    "expand_operand",
    "is_denied_credential_path",
    "resolve_confined_path",
    "resolve_tool_path",
    "resolved_within_root",
]
