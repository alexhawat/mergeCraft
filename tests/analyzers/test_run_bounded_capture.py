"""Analyzer capture is bounded while the pipes are read (#1566)."""

from __future__ import annotations

import sys
import time
import tracemalloc
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.analyzers import run as run_mod
from mergecraft.analyzers.resolve import AnalyzerPlan

if TYPE_CHECKING:
    from pathlib import Path

_CAP_BYTES = 64 * 1024
_EIGHT_MIB = 8 * 1024 * 1024
_SIXTY_FOUR_MIB = 64 * 1024 * 1024
_LINE = "x" * 1023 + "\n"


def _writer_script(total_bytes: int) -> str:
    """A child that writes ``total_bytes`` of newline-terminated lines to stdout."""
    return f"import sys\nline = {_LINE!r}\nfor _ in range({total_bytes // len(_LINE)}):\n    sys.stdout.write(line)\n"


def _both_streams_script(total_bytes: int) -> str:
    return (
        f"import sys\nline = {_LINE!r}\n"
        f"for _ in range({total_bytes // len(_LINE)}):\n"
        "    sys.stdout.write(line)\n"
        "    sys.stderr.write(line)\n"
    )


def _plan(tmp_path: Path, script: str, *, timeout_s: int = 120) -> AnalyzerPlan:
    return AnalyzerPlan(
        manifest_id="probe",
        argv=(sys.executable, "-c", script),
        cwd=tmp_path,
        mode="repo-native",
        timeout_s=timeout_s,
    )


@pytest.mark.timeout(120)
def test_parent_retains_at_most_the_cap_per_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_CHARS", _CAP_BYTES)
    handed: dict[str, int] = {}
    real_outcome = run_mod._outcome_from_completed

    def spy(*args: Any, **kwargs: Any) -> Any:
        completed = args[0]
        handed["stdout"] = len((completed.stdout or "").encode("utf-8"))
        handed["stderr"] = len((completed.stderr or "").encode("utf-8"))
        return real_outcome(*args, **kwargs)

    monkeypatch.setattr(run_mod, "_outcome_from_completed", spy)

    outcome = run_mod.run_plan(_plan(tmp_path, _both_streams_script(_EIGHT_MIB)))

    assert outcome.status == "passed"
    assert handed["stdout"] <= _CAP_BYTES
    assert handed["stderr"] <= _CAP_BYTES


@pytest.mark.timeout(180)
def test_peak_memory_is_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cap = 1024 * 1024
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_CHARS", cap)

    tracemalloc.start()
    try:
        outcome = run_mod.run_plan(_plan(tmp_path, _writer_script(_SIXTY_FOUR_MIB), timeout_s=180))
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert outcome.status == "passed"
    assert peak < 16 * 1024 * 1024


@pytest.mark.timeout(120)
def test_child_is_not_blocked_by_a_full_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reader that stops draining would block the child; it must keep reading."""
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_CHARS", _CAP_BYTES)

    started = time.monotonic()
    outcome = run_mod.run_plan(_plan(tmp_path, _writer_script(_EIGHT_MIB)))

    assert outcome.status == "passed"
    assert outcome.exit_code == 0
    assert time.monotonic() - started < 60


@pytest.mark.timeout(120)
def test_over_cap_stream_reports_the_exceeded_notice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(run_mod, "MAX_CAPTURED_OUTPUT_CHARS", _CAP_BYTES)

    outcome = run_mod.run_plan(_plan(tmp_path, _writer_script(_EIGHT_MIB)))

    assert "analyzer output exceeded" in outcome.output
    assert "chars per stream" in outcome.output


@pytest.mark.timeout(60)
def test_small_output_is_unchanged(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "import sys; sys.stdout.write('hello from the analyzer\\n')")

    outcome = run_mod.run_plan(plan)

    assert outcome.status == "passed"
    assert "hello from the analyzer" in outcome.output
    assert "analyzer output exceeded" not in outcome.output


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process groups")
@pytest.mark.timeout(60)
def test_timeout_still_kills_the_process_group(tmp_path: Path) -> None:
    plan = _plan(tmp_path, "import time; time.sleep(30)", timeout_s=1)

    started = time.monotonic()
    outcome = run_mod.run_plan(plan)

    assert outcome.status == "timed_out"
    assert time.monotonic() - started < 20
