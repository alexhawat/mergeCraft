"""Range coverage reaches the auditor and the one-time pre-submit nudge."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evidence.diff_coverage import LineRange
from mergecraft.evidence.trajectory import ToolCallRecord, build_trajectory_record, record_tool_call
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.mcp.verdict import diff_coverage_nudge_for_state

_DIFF = """\
diff --git a/src/app.py b/src/app.py
--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,3 @@
 one
+added
 two
diff --git a/src/other.py b/src/other.py
--- a/src/other.py
+++ b/src/other.py
@@ -10,2 +10,3 @@
 ten
+another
 eleven
"""


def _state_with_diff(tmp_path: Path, diff_text: str = _DIFF):
    diff_path = tmp_path / "pr-7.diff"
    diff_path.write_text(diff_text, encoding="utf-8")
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    repo = primary_repo_state(state)
    repo.diff_path = str(diff_path)
    repo.issue_number = 7
    return state, diff_path


def _read(state, command: str) -> None:
    record_tool_call(state, tool="shell", arguments={"command": command}, ok=True, outcome_ok=True)


def test_auditor_reports_unread_ranges_when_diff_is_supplied(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path)
    _read(state, f"sed -n '1,7p' {diff_path}")
    record = build_trajectory_record(state, files_modified=["src/app.py", "src/other.py"])

    findings = audit_trajectory(record, diff_text=_DIFF, diff_path=str(diff_path))
    unread = [row for row in findings if row.rule_id == "changed-unread-file"]

    assert unread, "reading half the diff must report the unread ranges"
    assert any("src/other.py" in row.message and "11-11" in row.message for row in unread)


def test_auditor_reports_nothing_when_every_range_was_read(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path)
    _read(state, f"cat {diff_path}")
    record = build_trajectory_record(state, files_modified=["src/app.py", "src/other.py"])

    findings = audit_trajectory(record, diff_text=_DIFF, diff_path=str(diff_path))

    assert not [row for row in findings if row.rule_id == "changed-unread-file"]


def test_auditor_keeps_file_level_behaviour_without_a_diff(tmp_path: Path) -> None:
    state, _diff_path = _state_with_diff(tmp_path)
    _read(state, "cat src/app.py")
    record = build_trajectory_record(state, files_modified=["src/app.py", "src/other.py"])

    findings = audit_trajectory(record)

    offender = next(row for row in findings if row.rule_id == "changed-unread-file")
    assert offender.path == "src/other.py"


def test_pre_submit_nudge_fires_once_and_names_ranges(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path)
    _read(state, f"sed -n '1,7p' {diff_path}")

    nudge = diff_coverage_nudge_for_state(state)

    assert nudge is not None
    assert "`src/other.py:11-11`" in nudge
    assert "one-time nudge" in nudge
    assert diff_coverage_nudge_for_state(state) is None


def test_pre_submit_nudge_stays_silent_without_read_evidence(tmp_path: Path) -> None:
    state, _diff_path = _state_with_diff(tmp_path)

    assert diff_coverage_nudge_for_state(state) is None


def test_nudge_accepts_already_built_tool_call_rows(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path)
    state.tool_calls.append(
        ToolCallRecord(
            sequence=1,
            tool="shell",
            signature="read:1",
            intent="read",
            ok=True,
            command=f"cat {diff_path}",
        )
    )

    assert diff_coverage_nudge_for_state(state) is None


def test_unread_range_type_is_public() -> None:
    assert LineRange(3, 4).line_count == 2
