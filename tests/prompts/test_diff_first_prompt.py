"""Item 1 — reviewer prompt reads the materialised diff first, never re-derives it."""

from __future__ import annotations

from pathlib import Path

from mergecraft.evidence.trajectory import build_trajectory_record, record_tool_call
from mergecraft.mcp.tool_state import init_tool_state
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


def test_fixture_trajectory_reads_the_diff_before_any_git_call() -> None:
    diff_path = "/tmp/mergecraft/pr-1017.diff"
    state = init_tool_state(owner="alexhawat", name="mergeCraft", dir="/work")
    state.repos[state.primary_repo_key].diff_path = diff_path
    record_tool_call(
        state,
        tool="checkout_pr",
        arguments={"pull_number": 1017},
        ok=True,
    )
    record_tool_call(
        state,
        tool="shell",
        arguments={"command": f"cat {diff_path}"},
        ok=True,
        outcome_ok=True,
    )
    record_tool_call(
        state,
        tool="git",
        arguments={"command": "diff", "args": ["origin/main..HEAD"]},
        ok=True,
    )
    record = build_trajectory_record(state)

    first_diff_read = next(
        index for index, call in enumerate(record.tool_calls) if call.diff_read_path is not None
    )
    first_git = next(index for index, call in enumerate(record.tool_calls) if call.tool == "git")

    assert first_diff_read < first_git
    assert record.tool_calls[first_diff_read].diff_read_path == diff_path
    assert _FIXTURE.is_file(), "the fixture trajectory must be checked in"
    assert diff_path in _FIXTURE.read_text(encoding="utf-8")


def test_review_and_incremental_templates_use_the_shared_marker() -> None:
    assert "${DIFF_FIRST_INSTRUCTION}" in Review.TEMPLATE
    assert "${DIFF_FIRST_INSTRUCTION}" in IncrementalReview.TEMPLATE
