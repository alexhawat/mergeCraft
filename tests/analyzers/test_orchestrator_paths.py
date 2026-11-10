"""Orchestrator-side analyzer files: lock record, scratch and persisted output.

The lock record stays at ``<checkout>/.mergecraft/analyzers.lock`` (it is a
documented artifact), so it is opened without following links. Scratch and
persisted output live under the per-process analyzer run root, outside the
checkout, and scratch is emptied for every run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from loguru import logger

from mergecraft.analyzers.lockfile import LockEntry, lock_digest, read_lock, write_lock
from mergecraft.analyzers.resolve import AnalyzerPlan
from mergecraft.analyzers.run import run_plan
from mergecraft.analyzers.sandbox import analyzer_run_root, fresh_analyzer_scratch_dir

if TYPE_CHECKING:
    from collections.abc import Iterator

_ENTRY = LockEntry(
    tool_id="actionlint", version="1.0.0", mode="managed", source="cache", sha256="a" * 64
)


@pytest.fixture
def warnings_sink() -> Iterator[list[str]]:
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="WARNING")
    yield captured
    logger.remove(sink_id)


def _tree_with_outside(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    return repo, outside


def test_symlinked_record_directory_is_refused(tmp_path: Path, warnings_sink: list[str]) -> None:
    repo, outside = _tree_with_outside(tmp_path)
    (repo / ".mergecraft").symlink_to(outside, target_is_directory=True)
    lock_path = repo / ".mergecraft" / "analyzers.lock"

    write_lock(lock_path, [_ENTRY], merge=True)

    assert list(outside.iterdir()) == []
    assert any("refusing analyzer lock record" in line for line in warnings_sink)


def test_symlinked_record_directory_is_not_read(tmp_path: Path) -> None:
    repo, outside = _tree_with_outside(tmp_path)
    write_lock(outside / "analyzers.lock", [_ENTRY])
    assert read_lock(outside / "analyzers.lock")
    (repo / ".mergecraft").symlink_to(outside, target_is_directory=True)

    assert read_lock(repo / ".mergecraft" / "analyzers.lock") == []
    assert lock_digest(repo / ".mergecraft" / "analyzers.lock") == "empty"


@pytest.mark.parametrize(
    "linked_name", ["analyzers.lock.lock", ".analyzers.lock.staging", "analyzers.lock"]
)
def test_symlinked_record_file_is_refused(
    tmp_path: Path, warnings_sink: list[str], linked_name: str
) -> None:
    repo, outside = _tree_with_outside(tmp_path)
    target = outside / "target"
    target.write_text("untouched\n", encoding="utf-8")
    (repo / ".mergecraft").mkdir()
    (repo / ".mergecraft" / linked_name).symlink_to(target)

    write_lock(repo / ".mergecraft" / "analyzers.lock", [_ENTRY], merge=True)

    assert target.read_text(encoding="utf-8") == "untouched\n"
    assert sorted(path.name for path in outside.iterdir()) == ["target"]
    if linked_name != ".analyzers.lock.staging":
        assert warnings_sink


def test_plain_record_directory_still_round_trips(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    lock_path = repo / ".mergecraft" / "analyzers.lock"
    write_lock(lock_path, [_ENTRY], merge=True)
    assert [entry.tool_id for entry in read_lock(lock_path)] == ["actionlint"]


def test_scratch_is_emptied_so_an_earlier_report_is_not_read(tmp_path: Path) -> None:
    scratch = fresh_analyzer_scratch_dir("jscpd")
    (scratch / "jscpd-report.json").write_text('{"duplicates": [1]}', encoding="utf-8")
    (scratch / "nested").mkdir()

    again = fresh_analyzer_scratch_dir("jscpd")

    assert again == scratch
    assert list(again.iterdir()) == []
    assert analyzer_run_root() in again.parents
    assert tmp_path.resolve() not in again.parents


def test_scratch_name_cannot_leave_the_run_root() -> None:
    scratch = fresh_analyzer_scratch_dir("../../escape")
    assert analyzer_run_root() in scratch.parents


def test_unwrapped_run_persists_output_outside_the_checkout(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".mergecraft").symlink_to(tmp_path / "outside", target_is_directory=True)
    plan = AnalyzerPlan(
        manifest_id="echo-gate",
        mode="repo-native",
        argv=("/bin/echo", "hello"),
        cwd=repo,
    )

    outcome = run_plan(plan, event_name="", event={})

    assert outcome.output_path is not None
    persisted = Path(outcome.output_path)
    assert analyzer_run_root() in persisted.parents
    assert not (tmp_path / "outside").exists()


def test_non_regular_record_is_refused_on_read_and_write(
    tmp_path: Path, warnings_sink: list[str]
) -> None:
    repo = tmp_path / "repo"
    (repo / ".mergecraft" / "analyzers.lock").mkdir(parents=True)
    lock_path = repo / ".mergecraft" / "analyzers.lock"

    assert read_lock(lock_path) == []
    assert lock_digest(lock_path) == "empty"
    write_lock(lock_path, [_ENTRY], merge=True)
    write_lock(lock_path, [_ENTRY], merge=False)

    assert lock_path.is_dir()
    assert list(lock_path.iterdir()) == []
    assert warnings_sink


@pytest.mark.parametrize("merge", [False, True])
@pytest.mark.parametrize("existing_record", [False, True])
def test_staging_directory_skips_write_without_changing_record(
    tmp_path: Path, warnings_sink: list[str], merge: bool, existing_record: bool
) -> None:
    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    lock_path.parent.mkdir()
    if existing_record:
        write_lock(lock_path, [_ENTRY])
    before = lock_path.read_bytes() if existing_record else None
    staging = lock_path.parent / ".analyzers.lock.staging"
    staging.mkdir()
    marker = staging / "keep.txt"
    marker.write_text("untouched\n", encoding="utf-8")
    replacement = LockEntry(
        tool_id="ruff", version="1.0.0", mode="managed", source="cache", sha256="b" * 64
    )

    write_lock(lock_path, [replacement], merge=merge)

    assert marker.read_text(encoding="utf-8") == "untouched\n"
    assert list(staging.iterdir()) == [marker]
    if existing_record:
        assert lock_path.read_bytes() == before
        assert read_lock(lock_path) == [_ENTRY]
    else:
        assert not lock_path.exists()
        assert read_lock(lock_path) == []
        assert lock_digest(lock_path) == "empty"
    assert any("lock record not written" in line for line in warnings_sink)


def test_record_read_io_error_is_treated_as_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings_sink: list[str]
) -> None:
    import mergecraft.analyzers.lockfile as lockfile

    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    write_lock(lock_path, [_ENTRY])

    def fail_read(dir_fd: int, name: str) -> list[LockEntry]:
        raise OSError("simulated read failure")

    monkeypatch.setattr(lockfile, "_read_in", fail_read)

    assert read_lock(lock_path) == []
    assert lock_digest(lock_path) == "empty"
    assert any("simulated read failure" in line for line in warnings_sink)


def test_record_replace_io_error_preserves_previous_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warnings_sink: list[str]
) -> None:
    import os

    lock_path = tmp_path / ".mergecraft" / "analyzers.lock"
    write_lock(lock_path, [_ENTRY])
    before = lock_path.read_bytes()

    def fail_replace(*args: object, **kwargs: object) -> None:
        raise PermissionError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    write_lock(lock_path, [])

    assert lock_path.read_bytes() == before
    assert read_lock(lock_path) == [_ENTRY]
    assert any("simulated replace failure" in line for line in warnings_sink)
    assert any("lock record not written" in line for line in warnings_sink)


@pytest.mark.parametrize("name", ["analyzers.lock", "analyzers.lock.lock"])
def test_fifo_record_is_refused_without_blocking(
    tmp_path: Path, warnings_sink: list[str], name: str
) -> None:
    import os

    repo = tmp_path / "repo"
    (repo / ".mergecraft").mkdir(parents=True)
    os.mkfifo(repo / ".mergecraft" / name)
    lock_path = repo / ".mergecraft" / "analyzers.lock"

    if name == "analyzers.lock":
        assert read_lock(lock_path) == []
    write_lock(lock_path, [_ENTRY], merge=True)

    assert warnings_sink
