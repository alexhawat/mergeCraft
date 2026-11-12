"""Interrupted run-cache writes leave the previous file intact.

The interruption is simulated at the rename, the last step of an atomic write:
if the content had been written in place, the destination would already be
truncated or half-written by then.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from mergecraft.utils import atomic_write
from mergecraft.utils.run_cache import RunCache

if TYPE_CHECKING:
    from pathlib import Path


class _Interrupted(Exception):
    pass


def _leftover_temps(directory: Path) -> list[str]:
    return [path.name for path in directory.rglob("*.tmp")]


def test_an_interrupted_cache_index_write_keeps_the_old_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache = RunCache(root=tmp_path, max_bytes=1_000_000)
    cache.put("first", b"one")
    before = (tmp_path / "index.json").read_text(encoding="utf-8")

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise _Interrupted

    monkeypatch.setattr(atomic_write.os, "replace", _raise)
    with pytest.raises(_Interrupted):
        cache.put("second", b"two")
    monkeypatch.undo()

    assert (tmp_path / "index.json").read_text(encoding="utf-8") == before
    assert cache.get("first") == b"one"
    assert _leftover_temps(tmp_path) == []


def test_a_malformed_index_row_is_skipped_not_raised(tmp_path: Path) -> None:
    cache = RunCache(root=tmp_path, max_bytes=1_000_000)
    cache.put("good", b"data")
    rows = json.loads((tmp_path / "index.json").read_text(encoding="utf-8"))
    (tmp_path / "index.json").write_text(
        json.dumps([{"path": "missing-key"}, "not-a-row", *rows]), encoding="utf-8"
    )

    assert cache.get("good") == b"data"
    assert cache.total_bytes() == 4
