"""File-backed run cache with a byte ceiling and cross-process locking (CC3)."""

from __future__ import annotations

import contextlib
import fcntl
import hashlib
import json
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator


@dataclass(slots=True)
class _CacheEntry:
    key: str
    path: str
    size: int
    mtime: float


class RunCache:
    """Byte-bounded on-disk cache safe for concurrent CLI runs over one root."""

    def __init__(self, *, root: Path, max_bytes: int) -> None:
        if max_bytes <= 0:
            msg = "max_bytes must be positive"
            raise ValueError(msg)
        self.root = root
        self.max_bytes = max_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        self._data_dir = self.root / "data"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._index_path = self.root / "index.json"
        self._lock_path = self.root / ".lock"

    def _key_path(self, key: str) -> Path:
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self._data_dir / digest

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self._lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _load_index(self) -> list[_CacheEntry]:
        if not self._index_path.is_file():
            return []
        try:
            raw: list[dict[str, Any]] = json.loads(self._index_path.read_text(encoding="utf-8"))
        except OSError, json.JSONDecodeError:
            return []
        entries: list[_CacheEntry] = []
        for row in raw:
            entries.append(
                _CacheEntry(
                    key=str(row["key"]),
                    path=str(row["path"]),
                    size=int(row["size"]),
                    mtime=float(row["mtime"]),
                )
            )
        return entries

    def _save_index(self, entries: list[_CacheEntry]) -> None:
        payload = [
            {
                "key": entry.key,
                "path": entry.path,
                "size": entry.size,
                "mtime": entry.mtime,
            }
            for entry in entries
        ]
        self._index_path.write_text(json.dumps(payload), encoding="utf-8")

    def total_bytes(self) -> int:
        with self._locked():
            return sum(entry.size for entry in self._load_index())

    def get(self, key: str) -> bytes | None:
        with self._locked():
            for entry in self._load_index():
                if entry.key != key:
                    continue
                path = Path(entry.path)
                if not path.is_file():
                    return None
                return path.read_bytes()
        return None

    def put(self, key: str, data: bytes) -> None:
        with self._locked():
            entries = [entry for entry in self._load_index() if entry.key != key]
            path = self._key_path(key)
            path.write_bytes(data)
            now = time.time()
            entries.append(_CacheEntry(key=key, path=str(path), size=len(data), mtime=now))
            self._evict_if_needed(entries)
            self._save_index(entries)

    def _evict_if_needed(self, entries: list[_CacheEntry]) -> None:
        total = sum(entry.size for entry in entries)
        if total <= self.max_bytes:
            return
        # Evict oldest entries first until under the ceiling.
        entries.sort(key=lambda entry: entry.mtime)
        while entries and total > self.max_bytes:
            victim = entries.pop(0)
            total -= victim.size
            with contextlib.suppress(OSError):
                Path(victim.path).unlink(missing_ok=True)

    def info(self) -> dict[str, Any]:
        with self._locked():
            entries = self._load_index()
            total = sum(entry.size for entry in entries)
            return {
                "root": str(self.root),
                "entries": len(entries),
                "bytes": total,
                "max_bytes": self.max_bytes,
            }

    def clear(self) -> int:
        with self._locked():
            entries = self._load_index()
            for entry in entries:
                with contextlib.suppress(OSError):
                    Path(entry.path).unlink(missing_ok=True)
            self._save_index([])
            return len(entries)

    def prune(self) -> int:
        with self._locked():
            entries = self._load_index()
            before = len(entries)
            self._evict_if_needed(entries)
            self._save_index(entries)
            return before - len(entries)


def default_cache_root() -> Path:
    """Return the on-disk run-cache root (``MERGECRAFT_CACHE_DIR`` or XDG default)."""
    raw = os.environ.get("MERGECRAFT_CACHE_DIR")
    if raw:
        return Path(raw).expanduser()
    return Path.home() / ".cache" / "mergecraft" / "run-cache"


def open_run_cache(*, root: Path, max_bytes: int) -> RunCache:
    return RunCache(root=root, max_bytes=max_bytes)


__all__ = ["RunCache", "default_cache_root", "open_run_cache"]
