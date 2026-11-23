"""Range coverage reaches the auditor and the one-time pre-submit nudge."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evidence.diff_coverage import LineRange
from mergecraft.evidence.trajectory import ToolCallRecord, build_trajectory_record, record_tool_call
from mergecraft.evidence.trajectory_audit import audit_trajectory
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.mcp.verdict import diff_coverage_nudge_for_state, review_depth_nudge_for_state

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


def test_pre_submit_nudge_names_everything_when_the_driver_reports_no_read(
    tmp_path: Path,
) -> None:
    state, _diff_path = _state_with_diff(tmp_path)
    state.driver_reports_reads = True

    nudge = diff_coverage_nudge_for_state(state)

    assert nudge is not None
    assert "`src/app.py:2-2`" in nudge
    assert "`src/other.py:11-11`" in nudge
    assert diff_coverage_nudge_for_state(state) is None


def test_pre_submit_nudge_stays_silent_on_a_generated_only_diff_with_no_read(
    tmp_path: Path,
) -> None:
    generated = (
        "diff --git a/uv.lock b/uv.lock\n--- a/uv.lock\n+++ b/uv.lock\n"
        "@@ -1,2 +1,3 @@\n one\n+added\n two\n"
    )
    state, _diff_path = _state_with_diff(tmp_path, generated)
    state.driver_reports_reads = True

    assert diff_coverage_nudge_for_state(state) is None


def test_a_paged_native_read_of_the_diff_silences_the_nudge(tmp_path: Path) -> None:
    from mergecraft.evidence.trajectory import record_driver_read

    state, diff_path = _state_with_diff(tmp_path)
    state.driver_reports_reads = True
    record_driver_read(state, path=str(diff_path), span=(1, 7))
    assert "src/other.py:11-11" in (diff_coverage_nudge_for_state(state) or "")

    state.diff_coverage_nudge_sent = False
    record_driver_read(state, path=str(diff_path), span=(8, 14))

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


def _large_diff(lines: int) -> str:
    added = "".join(f"+line {index}\n" for index in range(lines))
    return (
        "diff --git a/src/app.py b/src/app.py\n--- a/src/app.py\n+++ b/src/app.py\n"
        "@@ -1,2 +1,3 @@\n one\n+added\n two\n"
        "diff --git a/src/big.py b/src/big.py\n--- /dev/null\n+++ b/src/big.py\n"
        f"@@ -0,0 +1,{lines} @@\n{added}"
    )


def test_pre_submit_nudge_repeats_while_most_of_a_large_change_is_unread(tmp_path: Path) -> None:
    # #1516: one nudge, a quick page through the rest and a second submission was
    # all a verdict with most of a large diff unread had to survive.
    state, diff_path = _state_with_diff(tmp_path, _large_diff(400))
    _read(state, f"sed -n '1,7p' {diff_path}")

    first = diff_coverage_nudge_for_state(state)
    second = diff_coverage_nudge_for_state(state)
    third = diff_coverage_nudge_for_state(state)

    assert first is not None
    assert "400 of 401 added lines unread" in first
    assert "one-time nudge" not in first
    assert second is not None
    assert "fires again" in second
    assert third is not None
    assert "will not fire again" in third
    assert diff_coverage_nudge_for_state(state) is None


def test_pre_submit_nudge_stops_repeating_once_the_change_was_read(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path, _large_diff(400))
    _read(state, f"sed -n '1,7p' {diff_path}")
    assert diff_coverage_nudge_for_state(state) is not None

    _read(state, f"cat {diff_path}")

    assert diff_coverage_nudge_for_state(state) is None


def test_a_small_unread_remainder_still_gets_exactly_one_nudge(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path, _large_diff(150))
    _read(state, f"sed -n '1,7p' {diff_path}")

    assert "one-time nudge" in (diff_coverage_nudge_for_state(state) or "")
    assert diff_coverage_nudge_for_state(state) is None


def _read_source(state, *paths: str) -> None:
    for path in paths:
        record_tool_call(
            state,
            tool="git",
            arguments={"command": "show", "args": [f"HEAD:{path}"]},
            ok=True,
            outcome_ok=True,
        )


def test_a_large_change_reviewed_from_the_diff_alone_is_sent_back_once(tmp_path: Path) -> None:
    # #1516: every finding of a 10,000-line review came from the diff and three files.
    state, diff_path = _state_with_diff(tmp_path, _large_diff(1200))
    _read(state, f"cat {diff_path}")
    _read_source(state, "src/big.py")

    record_tool_call(
        state, tool="shell", arguments={"command": "cat src/missing.py"}, ok=True, outcome_ok=False
    )

    assert diff_coverage_nudge_for_state(state) is None
    nudge = review_depth_nudge_for_state(state)

    assert nudge is not None
    assert "a large change (1201 added lines across 2 files)" in nudge
    assert "opened 1 source file(s) beyond the diff" in nudge
    assert review_depth_nudge_for_state(state) is None


def test_a_large_change_whose_review_read_its_files_is_not_sent_back(tmp_path: Path) -> None:
    state, diff_path = _state_with_diff(tmp_path, _large_diff(1200))
    _read(state, f"cat {diff_path}")
    _read_source(state, "src/big.py", "src/app.py")

    assert review_depth_nudge_for_state(state) is None


def test_a_small_change_gets_no_depth_nudge_unless_it_is_high_risk(tmp_path: Path) -> None:
    from mergecraft.classify.blast_radius import classify_blast_radius

    state, diff_path = _state_with_diff(tmp_path)
    _read(state, f"cat {diff_path}")
    assert review_depth_nudge_for_state(state) is None

    classification = classify_blast_radius({"changed_paths": ["src/app.py"]})
    state.risk_classification = classification.model_copy(update={"lane": "high"})
    nudge = review_depth_nudge_for_state(state)

    assert nudge is not None
    assert "a high-risk change" in nudge


def test_an_unobserved_run_gets_no_depth_nudge(tmp_path: Path) -> None:
    state, _diff_path = _state_with_diff(tmp_path, _large_diff(1200))

    assert review_depth_nudge_for_state(state) is None


def test_the_packet_metrics_record_what_the_pre_flights_refused(tmp_path: Path) -> None:
    from types import SimpleNamespace

    from mergecraft.evidence.run_packet import _run_metrics

    state, diff_path = _state_with_diff(tmp_path, _large_diff(1200))
    _read(state, f"sed -n '1,7p' {diff_path}")
    assert diff_coverage_nudge_for_state(state) is not None
    _read(state, f"cat {diff_path}")
    assert diff_coverage_nudge_for_state(state) is None
    assert review_depth_nudge_for_state(state) is not None

    metrics = _run_metrics(
        SimpleNamespace(tool_state=state),
        trajectory=build_trajectory_record(state, files_modified=[]),
        diff_text=diff_path.read_text(encoding="utf-8"),
    )

    assert metrics.coverage_preflight_refusals == 1
    assert metrics.unread_added_lines_at_first_verdict == 1200
    assert metrics.depth_preflight_refused is True


def test_a_depth_refusal_is_guidance_not_an_ignored_tool_error(tmp_path: Path) -> None:
    state, _diff_path = _state_with_diff(tmp_path)
    record_tool_call(
        state,
        tool="submit_review_verdict",
        arguments={},
        ok=False,
        error="review depth pre-flight: this is a large change",
    )
    record = build_trajectory_record(state, files_modified=[])

    assert not [row for row in audit_trajectory(record) if row.rule_id == "ignored-tool-error"]
