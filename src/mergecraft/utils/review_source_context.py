"""Bounded source identity for optional local review-result reuse."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from typing import TYPE_CHECKING

from mergecraft.utils.git_hardening import git_argv
from mergecraft.utils.workspace import git_repo_root

if TYPE_CHECKING:
    from pathlib import Path

_MAX_FILES = 10_000
_MAX_BYTES = 64 * 1024 * 1024


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(
        git_argv(list(args)), cwd=root, capture_output=True, check=True, timeout=10
    ).stdout


def review_source_context_digest(*, cwd: Path, base_ref: str | None) -> str | None:
    """Hash revisions and tracked/nonignored source, or decline unsafe cache reuse.

    Gitignored artifacts are outside this identity. Unsupported workspaces,
    submodules, unreadable files and exceeded bounds disable optional caching.
    No file content or Git error output is exposed to the caller.
    """
    root = git_repo_root(str(cwd))
    if root is None:
        return None
    try:
        return _source_digest(root, base_ref=base_ref)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def _source_digest(root: Path, *, base_ref: str | None) -> str | None:
    digest = hashlib.sha256()
    # An unborn repository is a valid (empty) context; other unresolved refs
    # cannot identify the base materialized by the caller.
    try:
        head = _git(root, "rev-parse", "--verify", "--end-of-options", "HEAD^{commit}")
    except subprocess.CalledProcessError:
        _git(root, "symbolic-ref", "HEAD")
        head = b"unborn"
    digest.update(b"HEAD\0" + head)
    refs = base_ref.replace("...", "..").split("..") if base_ref else []
    for ref in refs:
        ref = ref or "HEAD"
        if ref == "HEAD" and head == b"unborn":
            continue
        base = _git(root, "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}")
        digest.update(b"base\0" + base)
    paths = sorted(
        set(_git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0"))
        - {b""}
    )
    if len(paths) > _MAX_FILES:
        return None
    remaining = _MAX_BYTES
    for raw_path in paths:
        path = root / os.fsdecode(raw_path)
        if not path.resolve().is_relative_to(root.resolve()):
            return None
        digest.update(b"\0path\0" + raw_path + b"\0")
        try:
            mode = path.lstat().st_mode
        except FileNotFoundError:
            digest.update(b"deleted")
            continue
        digest.update(str(stat.S_IMODE(mode)).encode() + b"\0")
        if stat.S_ISLNK(mode):
            content = os.fsencode(os.readlink(path))
        elif stat.S_ISREG(mode):
            with path.open("rb") as source:
                content = source.read(remaining + 1)
        else:
            return None
        remaining -= len(content)
        if remaining < 0:
            return None
        digest.update(hashlib.sha256(content).digest())
    return digest.hexdigest()
