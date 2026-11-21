"""A listing names files; it does not read them (#1520)."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evidence.trajectory import build_trajectory_record, record_tool_call
from mergecraft.mcp.tool_state import init_tool_state


def _state(tmp_path: Path):
    return init_tool_state(owner="acme", name="demo", dir=str(tmp_path))


def test_ls_files_operands_are_not_recorded_as_files_read(tmp_path: Path) -> None:
    state = _state(tmp_path)
    # One argument holding several space-separated paths, as a model sent it.
    record_tool_call(
        state,
        tool="git",
        arguments={"command": "ls-files", "args": ["docs src/api src/app.py notes.txt"]},
        ok=True,
        outcome_ok=True,
    )
    record_tool_call(
        state,
        tool="git",
        arguments={"command": "ls-files", "args": ["--", "src"]},
        ok=True,
        outcome_ok=True,
    )

    record = build_trajectory_record(state, files_modified=[])

    assert record.files_read == []
    assert all(call.paths == [] for call in record.tool_calls)


def test_a_git_read_of_a_file_is_still_recorded(tmp_path: Path) -> None:
    state = _state(tmp_path)
    record_tool_call(
        state,
        tool="git",
        arguments={"command": "show", "args": ["HEAD:src/app.py"]},
        ok=True,
        outcome_ok=True,
    )

    assert build_trajectory_record(state, files_modified=[]).files_read == ["src/app.py"]
