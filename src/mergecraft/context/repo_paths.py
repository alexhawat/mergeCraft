"""Bounded repo traversal with gitignore-style exclusions for context retrieval."""

from __future__ import annotations

import contextlib
import subprocess
import time
from pathlib import Path  # noqa: TC003 — used at runtime for repo traversal
from typing import IO, TYPE_CHECKING

from loguru import logger

from mergecraft.utils.git_hardening import git_argv

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

_EXCLUDED_DIR_NAMES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".tox",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".eggs",
        ".hypothesis",
        ".nox",
    }
)


def is_excluded_repo_path(rel_path: str) -> bool:
    """Return whether ``rel_path`` lies under a skipped directory segment."""
    return any(part in _EXCLUDED_DIR_NAMES for part in rel_path.split("/"))


def git_ls_tree_paths(
    repo_root: Path,
    tree_sha: str,
    *,
    suffix: str = "",
) -> list[str]:
    """List tracked paths under ``tree_sha``, applying context exclusions."""
    try:
        completed = subprocess.run(
            git_argv(["ls-tree", "-r", "--name-only", tree_sha]),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        logger.debug("git ls-tree unavailable for tree {}", tree_sha)
        return []
    if completed.returncode != 0:
        logger.debug("git ls-tree failed for tree {}: {}", tree_sha, completed.stderr.strip())
        return []

    paths: list[str] = []
    for rel_path in completed.stdout.splitlines():
        if not rel_path or is_excluded_repo_path(rel_path):
            continue
        if suffix and not rel_path.endswith(suffix):
            continue
        paths.append(rel_path)
    return sorted(paths)


def _read_exactly(stream: IO[bytes], size: int) -> bytes | None:
    """Read ``size`` bytes from a binary stream, or ``None`` on short read."""
    buf = bytearray()
    remaining = size
    while remaining > 0:
        chunk = stream.read(remaining)
        if not chunk:
            return None
        buf.extend(chunk)
        remaining -= len(chunk)
    return bytes(buf)


def _git_show_text_bounded(repo_root: Path, spec: str, max_bytes: int) -> str | None:
    """Return blob text at ``spec`` without buffering more than ``max_bytes``.

    Uses ``git cat-file --batch`` so the size is known from the header before
    any payload is retained. Oversized blobs are dropped by killing the helper
    rather than reading the object into memory.
    """
    try:
        proc = subprocess.Popen(
            git_argv(["cat-file", "--batch"]),
            cwd=repo_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return None
    try:
        if proc.stdin is None or proc.stdout is None:
            return None
        proc.stdin.write(f"{spec}\n".encode())
        proc.stdin.close()
        header = proc.stdout.readline()
        if not header or b" missing" in header:
            return None
        parts = header.split()
        if len(parts) < 3:
            return None
        try:
            size = int(parts[-1])
        except ValueError:
            return None
        if size > max_bytes:
            return None
        raw = _read_exactly(proc.stdout, size)
        if raw is None:
            return None
        proc.stdout.read(1)
        if b"\x00" in raw:
            return None
        return raw.decode("utf-8", errors="replace")
    finally:
        proc.kill()
        with contextlib.suppress(OSError, subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def git_show_text(
    repo_root: Path,
    tree_sha: str,
    rel_path: str,
    *,
    max_bytes: int | None = None,
) -> str | None:
    """Return file text at ``tree_sha:rel_path``, or ``None`` when absent or binary.

    Reads bytes and decodes with replacement so a PNG or other non-UTF-8 blob
    cannot raise ``UnicodeDecodeError`` and abort a whole tree walk.

    When ``max_bytes`` is set, the blob size is taken from ``git cat-file
    --batch`` and payloads larger than the cap are skipped without buffering
    the object.
    """
    spec = f"{tree_sha}:{rel_path}"
    if max_bytes is not None:
        return _git_show_text_bounded(repo_root, spec, max_bytes)
    try:
        completed = subprocess.run(
            git_argv(["show", spec]),
            cwd=repo_root,
            capture_output=True,
            check=False,
        )
    except OSError:
        return None
    if completed.returncode != 0:
        return None
    raw = completed.stdout
    if b"\x00" in raw:
        return None
    return raw.decode("utf-8", errors="replace")


def git_blob_sha(repo_root: Path, tree_sha: str, rel_path: str) -> str:
    """Return the git blob SHA for ``rel_path`` at ``tree_sha``."""
    try:
        completed = subprocess.run(
            git_argv(["rev-parse", f"{tree_sha}:{rel_path}"]),
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        completed = None
    if completed is not None and completed.returncode == 0:
        return completed.stdout.strip()
    shown = git_show_text(repo_root, tree_sha, rel_path)
    if shown is None:
        return f"missing:{tree_sha}:{rel_path}"
    return f"blob:{shown.encode('utf-8').hex()[:40]}"


def iter_repo_files(
    repo_root: Path,
    *,
    predicate: Callable[[Path], bool] | None = None,
    deadline: float | None = None,
) -> Iterator[str]:
    """Walk ``repo_root`` with exclusions and an optional monotonic deadline."""
    for path in sorted(repo_root.rglob("*")):
        if deadline is not None and time.monotonic() > deadline:
            logger.warning("context retrieval scan timed out under {}", repo_root)
            return
        if not path.is_file():
            continue
        rel = path.relative_to(repo_root).as_posix()
        if is_excluded_repo_path(rel):
            continue
        if predicate is not None and not predicate(path):
            continue
        yield rel


__all__ = [
    "git_blob_sha",
    "git_ls_tree_paths",
    "git_show_text",
    "is_excluded_repo_path",
    "iter_repo_files",
]
