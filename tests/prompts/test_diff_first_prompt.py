"""Item 1 — reviewer prompt reads the materialised diff first, never re-derives it."""

from __future__ import annotations

import json
from pathlib import Path

from mergecraft.evidence.trajectory import ToolCallRecord, TrajectoryRecord
from mergecraft.modes import IncrementalReview, Review, compute_modes

_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "diff_first_trajectory.json"


def _rendered(name: str) -> str:
    for mode in compute_modes("claude"):
        if mode.name == name:
            assert mode.prompt is not None
            return mode.prompt
    msg = f"mode {name!r} missing"
    raise AssertionError(msg)


def test_review_prompt_pins_diff_first_scope() -> None:
    prompt = _rendered("Review")

    assert (
        "Read `mcp__mergecraft__checkout_pr`'s returned `diffPath` as your first action" in prompt
    )
    assert "Do **not** run `git diff`, `git grep`, or `git log`" in prompt
    assert "Batch every independent read/grep/glob into a single turn" in prompt
    assert "${DIFF_FIRST_INSTRUCTION}" not in prompt


def test_incremental_review_prompt_pins_diff_first_scope() -> None:
    prompt = _rendered("IncrementalReview")

    assert (
        "Read `mcp__mergecraft__checkout_pr`'s returned `diffPath` as your first action" in prompt
    )
    assert "Do **not** run `git diff`, `git grep`, or `git log`" in prompt
    assert "incrementalDiffPath" in prompt
    assert "${DIFF_FIRST_INSTRUCTION}" not in prompt


def test_scope_block_precedes_the_checklist() -> None:
    prompt = _rendered("Review")

    assert prompt.index("### Scope discipline (hard rule)") < prompt.index("### Checklist")


def test_incremental_prompt_scopes_to_the_delta_not_the_whole_pr() -> None:
    prompt = _rendered("IncrementalReview")

    assert "it is the review scope" in prompt
    assert "do not re-read the whole PR" in prompt
    assert "incrementalDiffStatus" in prompt
    assert "incrementalDiffReason" in prompt
    assert "`empty`, nothing changed since the last review" in prompt
    assert "do **not** run `git diff <prior-review-sha>..HEAD`" in prompt


def test_review_prompt_still_submits_a_verdict_when_the_delta_is_empty() -> None:
    # Review mode has no report_progress exit, and a Review run without a
    # terminal submission is classified inconclusive — so an empty delta must
    # still end in a verdict rather than a progress-only report.
    prompt = _rendered("Review")

    assert "`incrementalDiffStatus: empty`, nothing changed since the last review" in prompt
    assert "this mode has no progress-only exit" in prompt
    assert "finish with the terminal verdict in step 7" in prompt
    assert "report progress instead of re-reading" not in prompt


def test_fixture_trajectory_reads_the_diff_before_any_git_call() -> None:
    diff_path = "/tmp/mergecraft/pr-1017.diff"
    fixture = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    record = TrajectoryRecord(
        tool_calls=[ToolCallRecord.model_validate(row) for row in fixture["tool_calls"]],
        read_coverage=True,
    )

    first_diff_read = next(
        index for index, call in enumerate(record.tool_calls) if call.diff_read_path is not None
    )
    first_git = next(index for index, call in enumerate(record.tool_calls) if call.tool == "git")

    assert first_diff_read < first_git
    assert record.tool_calls[first_diff_read].diff_read_path == diff_path
    assert diff_path in _FIXTURE.read_text(encoding="utf-8")


def test_review_and_incremental_templates_use_the_shared_marker() -> None:
    assert "${DIFF_FIRST_INSTRUCTION}" in Review.TEMPLATE
    assert "${DIFF_FIRST_INSTRUCTION}" in IncrementalReview.TEMPLATE
