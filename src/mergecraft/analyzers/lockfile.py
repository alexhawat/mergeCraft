"""Analyzer lockfile — reproducible tool resolution (D24)."""

from __future__ import annotations

import contextlib
import fcntl
import os
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import yaml
from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LockMode = Literal["repo-native", "ci-result", "managed", "container"]

#: Keys a lock row must carry before it can become a :class:`LockEntry`. The lock
#: is written inside the tree a review runs over, so a row may arrive malformed.
_REQUIRED_ENTRY_KEYS = ("tool_id", "version", "sha256")


@contextlib.contextmanager
def _lockfile_transaction(path: Path) -> Iterator[None]:
    """Serialize lockfile read/modify/write across parallel analyzer runs.

    The lock is a sidecar file, never the data file itself: the write path
    replaces the data file atomically, and a ``flock`` held on the file being
    replaced would orphan every waiter onto the old inode.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f"{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as handle:
        if sys.platform != "win32":
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform != "win32":
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def read_lock(path: Path) -> list[LockEntry]:
    """Read ``.mergecraft/analyzers.lock`` entries."""
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return []
    tools = data.get("tools")
    if not isinstance(tools, list):
        return []
    return _coerce_entries(tools)


def write_lock(
    path: Path,
    entries: list[LockEntry | dict[str, Any]],
    *,
    merge: bool = False,
) -> None:
    """Write lock entries; ``merge`` retains other tool ids already on disk.

    The payload is staged to a sibling temp file and moved into place with
    ``os.replace`` while the sidecar lock is held, so a failure part-way through
    leaves the previous record intact instead of a truncated one.
    """
    normalized = [
        entry if isinstance(entry, LockEntry) else _coerce_entry(entry) for entry in entries
    ]
    with _lockfile_transaction(path):
        if merge:
            by_id = {entry.tool_id: entry for entry in read_lock(path)}
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
        staging = path.with_name(f".{path.name}.staging")
        staging.write_text(text, encoding="utf-8")
        os.replace(staging, path)


def lock_digest(path: Path) -> str:
    """Short digest for review preambles."""
    entries = read_lock(path)
    if not entries:
        return "empty"
    joined = "|".join(f"{entry.tool_id}@{entry.sha256[:12]}" for entry in entries)
    import hashlib

    return hashlib.sha256(joined.encode()).hexdigest()[:16]


__all__ = ["LockEntry", "LockMode", "lock_digest", "read_lock", "write_lock"]
