"""Analyzer lockfile — reproducible tool resolution (D24)."""

from __future__ import annotations

import contextlib
import fcntl
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LockMode = Literal["repo-native", "ci-result", "managed", "container"]


@contextlib.contextmanager
def _lockfile_transaction(path: Path) -> Iterator[None]:
    """Serialize lockfile read/modify/write across parallel analyzer runs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
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
        mode=str(raw.get("mode", "managed")),  # type: ignore[arg-type]
        source=str(raw.get("source", "unknown")),
        sha256=str(raw["sha256"]),
    )


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
    entries: list[LockEntry] = []
    for item in tools:
        if isinstance(item, dict):
            entries.append(_coerce_entry(item))
    return entries


def write_lock(
    path: Path,
    entries: list[LockEntry | dict[str, Any]],
    *,
    merge: bool = False,
) -> None:
    """Write lock entries; ``merge`` retains other tool ids already on disk."""
    normalized = [
        entry if isinstance(entry, LockEntry) else _coerce_entry(entry) for entry in entries
    ]
    with _lockfile_transaction(path):
        if merge and path.is_file():
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
        path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def lock_digest(path: Path) -> str:
    """Short digest for review preambles."""
    entries = read_lock(path)
    if not entries:
        return "empty"
    joined = "|".join(f"{entry.tool_id}@{entry.sha256[:12]}" for entry in entries)
    import hashlib

    return hashlib.sha256(joined.encode()).hexdigest()[:16]


__all__ = ["LockEntry", "LockMode", "lock_digest", "read_lock", "write_lock"]
