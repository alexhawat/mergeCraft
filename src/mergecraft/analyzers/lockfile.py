"""Analyzer lockfile — reproducible tool resolution (D24)."""

from __future__ import annotations

import contextlib
import fcntl
import os
import stat
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import yaml
from loguru import logger

from mergecraft.utils.file_lock import acquire_file_lock

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LockMode = Literal["repo-native", "ci-result", "managed", "container"]

#: Keys a lock row must carry before it can become a :class:`LockEntry`. The lock
#: is written inside the tree a review runs over, so a row may arrive malformed.
_REQUIRED_ENTRY_KEYS = ("tool_id", "version", "sha256")


_CLOEXEC = getattr(os, "O_CLOEXEC", 0)
_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)
_NONBLOCK = getattr(os, "O_NONBLOCK", 0)


class LockPathRefusedError(OSError):
    """The lock record's directory or file is a symbolic link, so it is not used."""


def _open_record_dir(path: Path, *, create: bool) -> int | None:
    """Open the directory holding ``path`` without following a link in its place.

    The lock record sits at ``<checkout>/.mergecraft/analyzers.lock``, inside the
    tree under review, so the ``.mergecraft`` component may be anything a PR
    committed. It is opened relative to its parent with ``O_NOFOLLOW``; a link
    there raises :class:`LockPathRefusedError` instead of being followed. Every
    later open, rename and unlink is relative to the returned descriptor, so no
    path is re-resolved. Returns ``None`` when the directory is absent and
    ``create`` is false.
    """
    parent = path.parent
    if create:
        parent.parent.mkdir(parents=True, exist_ok=True)
    try:
        anchor = os.open(parent.parent, os.O_RDONLY | os.O_DIRECTORY | _CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        if create:
            with contextlib.suppress(FileExistsError):
                os.mkdir(parent.name, 0o755, dir_fd=anchor)
        try:
            return os.open(
                parent.name, os.O_RDONLY | os.O_DIRECTORY | _NOFOLLOW | _CLOEXEC, dir_fd=anchor
            )
        except FileNotFoundError:
            return None
        except OSError as exc:
            msg = f"refusing analyzer lock record directory {parent}: not a plain directory ({exc})"
            raise LockPathRefusedError(msg) from exc
    finally:
        os.close(anchor)


def _open_in(dir_fd: int, name: str, flags: int, mode: int = 0o644) -> int:
    """``open`` ``name`` relative to ``dir_fd``; refuse anything but a regular file.

    ``O_NONBLOCK`` keeps the open from waiting on a FIFO; the opened descriptor
    is then checked with ``fstat`` so a directory, FIFO, socket or device is
    refused the same way a symbolic link is.
    """
    try:
        fd = os.open(name, flags | _NOFOLLOW | _CLOEXEC | _NONBLOCK, mode, dir_fd=dir_fd)
    except FileNotFoundError:
        raise
    except OSError as exc:
        msg = f"refusing analyzer lock record file {name}: not a regular file ({exc})"
        raise LockPathRefusedError(msg) from exc
    try:
        is_regular = stat.S_ISREG(os.fstat(fd).st_mode)
        if is_regular and _NONBLOCK:
            os.set_blocking(fd, True)
    except OSError as exc:
        os.close(fd)
        msg = f"refusing analyzer lock record file {name}: cannot inspect it ({exc})"
        raise LockPathRefusedError(msg) from exc
    if not is_regular:
        os.close(fd)
        msg = f"refusing analyzer lock record file {name}: not a regular file"
        raise LockPathRefusedError(msg)
    return fd


def _require_regular_or_absent(dir_fd: int, name: str) -> None:
    """Refuse to replace ``name`` unless it is absent or a regular file."""
    try:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISREG(info.st_mode):
        msg = f"refusing analyzer lock record file {name}: not a regular file"
        raise LockPathRefusedError(msg)


@contextlib.contextmanager
def _lockfile_transaction(path: Path) -> Iterator[int]:
    """Serialize lockfile read/modify/write across parallel analyzer runs.

    The lock is a sidecar file, never the data file itself: the write path
    replaces the data file atomically, and a ``flock`` held on the file being
    replaced would orphan every waiter onto the old inode. Yields the record
    directory's descriptor; nothing under it is reached through a link.
    """
    dir_fd = _open_record_dir(path, create=True)
    if dir_fd is None:  # pragma: no cover - created above
        msg = f"analyzer lock record directory {path.parent} could not be created"
        raise LockPathRefusedError(msg)
    try:
        lock_fd = _open_in(dir_fd, f"{path.name}.lock", os.O_RDWR | os.O_CREAT)
        try:
            if sys.platform != "win32":
                acquire_file_lock(lock_fd)
            try:
                yield dir_fd
            finally:
                if sys.platform != "win32":
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(lock_fd)
    finally:
        os.close(dir_fd)


@dataclass(frozen=True, slots=True)
class LockEntry:
    tool_id: str
    version: str
    mode: LockMode
    source: str
    sha256: str


def _coerce_entry(raw: dict[str, Any]) -> LockEntry:
    return LockEntry(
        tool_id=str(raw["tool_id"]),
        version=str(raw["version"]),
        mode=str(raw.get("mode", "managed")),  # type: ignore[arg-type]  # — mode is str from JSON; LockEntry.mode is a Literal narrowing enforced by the schema
        source=str(raw.get("source", "unknown")),
        sha256=str(raw["sha256"]),
    )


def _coerce_entries(raws: Any) -> list[LockEntry]:
    """Coerce lock rows, skipping (with a warning) any row missing a required key.

    The lock lives in the tree under review, so a malformed row a PR committed
    must never abort a run — it is dropped, not raised.
    """
    entries: list[LockEntry] = []
    for item in raws:
        if not isinstance(item, dict):
            continue
        missing = [key for key in _REQUIRED_ENTRY_KEYS if key not in item]
        if missing:
            logger.warning(
                "skipping malformed lock row (missing {}): {!r}",
                ", ".join(missing),
                item,
            )
            continue
        entries.append(_coerce_entry(item))
    return entries


def _parse_lock_text(text: str) -> list[LockEntry]:
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return []
    tools = data.get("tools")
    if not isinstance(tools, list):
        return []
    return _coerce_entries(tools)


def _read_in(dir_fd: int, name: str) -> list[LockEntry]:
    try:
        fd = _open_in(dir_fd, name, os.O_RDONLY)
    except FileNotFoundError:
        return []
    with os.fdopen(fd, encoding="utf-8") as handle:
        return _parse_lock_text(handle.read())


def read_lock(path: Path) -> list[LockEntry]:
    """Read ``.mergecraft/analyzers.lock`` entries.

    A record directory or file that is a symbolic link, or a record that is not
    a regular file, is refused with a warning and reads as empty. Other I/O
    failures also warn and read as empty; this record is only informational.
    """
    try:
        dir_fd = _open_record_dir(path, create=False)
        if dir_fd is None:
            return []
        try:
            return _read_in(dir_fd, path.name)
        finally:
            os.close(dir_fd)
    except OSError as exc:
        logger.warning("{}", exc)
        return []


def write_lock(
    path: Path,
    entries: list[LockEntry | dict[str, Any]],
    *,
    merge: bool = False,
) -> None:
    """Write lock entries; ``merge`` retains other tool ids already on disk.

    The payload is staged to a sibling temp file and moved into place with
    ``os.replace`` while the sidecar lock is held, so a failure part-way through
    leaves the previous record intact instead of a truncated one. Every file is
    opened relative to the record directory without following links; when that
    directory, the record, its sidecar or the staging file is a symbolic link the
    write is refused with a warning and nothing is written. Other I/O failures,
    including a directory occupying the staging path, also warn and skip the
    record write rather than aborting the analyzer run.
    """
    normalized = [
        entry if isinstance(entry, LockEntry) else _coerce_entry(entry) for entry in entries
    ]
    try:
        with _lockfile_transaction(path) as dir_fd:
            if merge:
                by_id = {entry.tool_id: entry for entry in _read_in(dir_fd, path.name)}
                for entry in normalized:
                    by_id[entry.tool_id] = entry
                normalized = list(by_id.values())

            payload = {
                "version": 1,
                "tools": [
                    {
                        "tool_id": entry.tool_id,
                        "version": entry.version,
                        "mode": entry.mode,
                        "source": entry.source,
                        "sha256": entry.sha256,
                    }
                    for entry in normalized
                ],
            }
            text = yaml.safe_dump(payload, sort_keys=False)
            staging = f".{path.name}.staging"
            with contextlib.suppress(FileNotFoundError):
                os.unlink(staging, dir_fd=dir_fd)
            fd = _open_in(dir_fd, staging, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
            _require_regular_or_absent(dir_fd, path.name)
            os.replace(staging, path.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd)
    except OSError as exc:
        # The record is never an authenticator (binaries are verified against
        # pin-bound receipts), so a refused record skips the write, not the run.
        logger.warning("{}; lock record not written", exc)


def lock_digest(path: Path) -> str:
    """Short digest for review preambles."""
    entries = read_lock(path)
    if not entries:
        return "empty"
    joined = "|".join(f"{entry.tool_id}@{entry.sha256[:12]}" for entry in entries)
    import hashlib

    return hashlib.sha256(joined.encode()).hexdigest()[:16]


__all__ = [
    "LockEntry",
    "LockMode",
    "LockPathRefusedError",
    "lock_digest",
    "read_lock",
    "write_lock",
]
