"""Lockfile robustness — a malformed row must never abort an analyzer run.

``.mergecraft/analyzers.lock`` is written inside the tree a review runs over, so
a row with a missing key used to reach ``LockEntry`` and raise ``KeyError`` out
of ``read_lock``, ``lock_digest`` and a merging ``write_lock``. A crashed write
must leave the previous record intact rather than a truncated one, and
concurrent writers must still serialise.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from loguru import logger

from mergecraft.analyzers.lockfile import (
    LockEntry,
    lock_digest,
    read_lock,
    write_lock,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

_GOOD_SHA = "a" * 64
_BAD_SHA = "b" * 64

# Each row is a YAML ``tools:`` item missing exactly one required key.
_MALFORMED_ROWS: dict[str, str] = {
    "tool_id": "- version: 1.0.0\n  mode: managed\n  source: cache\n  sha256: {sha}\n",
    "version": "- tool_id: broken\n  mode: managed\n  source: cache\n  sha256: {sha}\n",
    "sha256": "- tool_id: broken\n  version: 1.0.0\n  mode: managed\n  source: cache\n",
}

_WELL_FORMED_ROW = "- tool_id: actionlint\n  version: 1.7.12\n  mode: managed\n  source: cache\n"


def _lock_text(rows: str) -> str:
    return f"version: 1\ntools:\n{rows}"


def _entry(tool_id: str, *, sha256: str = _GOOD_SHA) -> LockEntry:
    return LockEntry(
        tool_id=tool_id,
        version="1.0.0",
        mode="managed",
        source="cache",
        sha256=sha256,
    )


def _write_rows(path: Path, rows: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_lock_text(rows), encoding="utf-8")


@pytest.fixture
def warnings_sink() -> Iterator[list[str]]:
    """Capture loguru WARNING+ records so "skipped with a warning" is assertable."""
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    try:
        yield captured
    finally:
        logger.remove(sink_id)


@pytest.mark.parametrize("missing", sorted(_MALFORMED_ROWS))
def test_read_lock_skips_a_row_missing_a_required_key(
    tmp_path: Path, missing: str, warnings_sink: list[str]
) -> None:
    """A row without ``tool_id`` / ``version`` / ``sha256`` is dropped, not raised."""
    path = tmp_path / ".mergecraft" / "analyzers.lock"
    _write_rows(path, _MALFORMED_ROWS[missing].format(sha=_BAD_SHA))

    assert read_lock(path) == []
    assert warnings_sink, f"a lock row missing {missing!r} was dropped without a warning"


def test_read_lock_keeps_well_formed_rows_beside_a_malformed_one(tmp_path: Path) -> None:
    """One broken row must not take its well-formed siblings down with it."""
    path = tmp_path / ".mergecraft" / "analyzers.lock"
    rows = _MALFORMED_ROWS["version"].format(sha=_BAD_SHA) + (
        f"{_WELL_FORMED_ROW}  sha256: {_GOOD_SHA}\n"
    )
    _write_rows(path, rows)

    assert [entry.tool_id for entry in read_lock(path)] == ["actionlint"]


def test_lock_digest_skips_a_malformed_row_instead_of_raising(tmp_path: Path) -> None:
    """The pre-merge digest reads the same rows, so it needs the same tolerance."""
    path = tmp_path / ".mergecraft" / "analyzers.lock"
    _write_rows(path, _MALFORMED_ROWS["tool_id"].format(sha=_BAD_SHA))

    assert lock_digest(path) == "empty"


def test_merging_write_skips_a_malformed_row_already_on_disk(
    tmp_path: Path, warnings_sink: list[str]
) -> None:
    """A merge must not crash on a row it has to read back before it writes."""
    path = tmp_path / ".mergecraft" / "analyzers.lock"
    _write_rows(path, _MALFORMED_ROWS["version"].format(sha=_BAD_SHA))

    write_lock(path, [_entry("actionlint")], merge=True)

    assert [entry.tool_id for entry in read_lock(path)] == ["actionlint"]
    assert warnings_sink


def test_failed_write_leaves_the_previous_lock_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A crash mid-write must not truncate the record it was replacing."""
    import mergecraft.analyzers.lockfile as lockfile

    path = tmp_path / ".mergecraft" / "analyzers.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_lock(path, [_entry("actionlint")])
    before = path.read_text(encoding="utf-8")
    assert before.strip(), "fixture did not write a lock to protect"

    def _fail(*_args: object, **_kwargs: object) -> str:
        msg = "simulated serialisation failure"
        raise RuntimeError(msg)

    monkeypatch.setattr(lockfile.yaml, "safe_dump", _fail)

    with pytest.raises(RuntimeError, match="simulated serialisation failure"):
        write_lock(path, [_entry("ruff")])

    assert path.read_text(encoding="utf-8") == before


def test_concurrent_merging_writers_still_serialise(tmp_path: Path) -> None:
    """Parallel analyzer runs must not lose each other's lock rows."""
    path = tmp_path / ".mergecraft" / "analyzers.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    tool_ids = [f"tool-{index}" for index in range(4)]
    failures: list[BaseException] = []

    def _write(tool_id: str) -> None:
        try:
            for _ in range(5):
                write_lock(path, [_entry(tool_id)], merge=True)
        except BaseException as exc:  # surfaced by the assertion below
            failures.append(exc)

    threads = [threading.Thread(target=_write, args=(tool_id,)) for tool_id in tool_ids]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert {entry.tool_id for entry in read_lock(path)} == set(tool_ids)
