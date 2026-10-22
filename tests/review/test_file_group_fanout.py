"""Slice 5 — bounded file-group fan-out plans and degrades, never fails a run."""

from __future__ import annotations

import asyncio

from mergecraft.review.file_group_fanout import (
    FileGroup,
    dispatch_file_groups,
    plan_file_groups,
)


def _diff(file_count: int, lines_per_file: int) -> str:
    chunks: list[str] = []
    for index in range(file_count):
        added = "\n".join(f"+line {line}" for line in range(lines_per_file))
        chunks.append(
            f"diff --git a/src/f{index}.py b/src/f{index}.py\n"
            f"--- a/src/f{index}.py\n"
            f"+++ b/src/f{index}.py\n"
            f"@@ -0,0 +1,{lines_per_file} @@\n{added}\n"
        )
    return "".join(chunks)


def test_large_diff_fans_into_a_bounded_number_of_groups() -> None:
    plan = plan_file_groups(_diff(30, 30), max_groups=4)

    assert plan.enabled is True
    assert len(plan.groups) == 4
    assert sum(len(group.paths) for group in plan.groups) == 30
    assert len({path for group in plan.groups for path in group.paths}) == 30
    assert all(group.diff_lines > 0 for group in plan.groups)


def test_small_diff_keeps_the_single_agent_path() -> None:
    plan = plan_file_groups(_diff(2, 5))

    assert plan.enabled is False
    assert plan.groups == ()
    assert "below the fan-out threshold" in plan.reason


def test_a_failed_group_is_recorded_not_raised() -> None:
    plan = plan_file_groups(_diff(30, 30), max_groups=3)
    recorded: list[tuple[str, str]] = []

    async def _dispatch(group: FileGroup) -> str:
        if group.group_id == "group-2":
            raise RuntimeError("provider unavailable")
        return f"ok:{group.group_id}"

    summary = asyncio.run(
        dispatch_file_groups(
            plan, _dispatch, on_failure=lambda gid, why: recorded.append((gid, why))
        )
    )

    assert summary.degraded is True
    assert summary.failures == (("group-2", "provider unavailable"),)
    assert recorded == [("group-2", "provider unavailable")]
    assert len(summary.results) == 2


def test_empty_plan_does_not_call_the_dispatcher() -> None:
    plan = plan_file_groups(_diff(1, 1))
    called: list[FileGroup] = []

    async def _dispatch(group: FileGroup) -> str:
        called.append(group)
        return group.group_id

    summary = asyncio.run(dispatch_file_groups(plan, _dispatch))

    assert summary == type(summary)()
    assert called == []
