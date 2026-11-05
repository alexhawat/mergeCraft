"""Slice 5 — bounded file-group fan-out plans and degrades, never fails a run."""

from __future__ import annotations

import asyncio

import pytest

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


# --------------------------------------------------------------------------- thresholds
#
# Fan-out triggers when EITHER threshold is met: ``min_files`` changed files or
# ``min_diff_lines`` added lines. Below both, the single-agent path stays.


@pytest.mark.parametrize(
    ("file_count", "lines_per_file", "fans_out"),
    [
        pytest.param(25, 10, True, id="25-files-x-10-lines-meets-the-file-threshold"),
        pytest.param(5, 200, True, id="5-files-x-200-lines-meets-the-line-threshold"),
        pytest.param(5, 10, False, id="5-files-x-10-lines-is-below-both"),
        pytest.param(20, 1, True, id="exactly-20-files"),
        pytest.param(1, 800, True, id="exactly-800-added-lines-in-one-file"),
        pytest.param(19, 42, False, id="19-files-and-798-lines"),
    ],
)
def test_either_threshold_triggers_fanout(
    file_count: int, lines_per_file: int, fans_out: bool
) -> None:
    plan = plan_file_groups(_diff(file_count, lines_per_file))

    assert plan.enabled is fans_out
    if fans_out:
        assert sum(len(group.paths) for group in plan.groups) == file_count
    else:
        assert plan.groups == ()
        assert f"{file_count} files" in plan.reason
        assert f"{file_count * lines_per_file} added lines" in plan.reason


def test_thresholds_are_caller_supplied() -> None:
    """The settings' ``minFiles`` / ``minDiffLines`` reach the planner as keywords."""
    diff = _diff(5, 10)

    assert plan_file_groups(diff).enabled is False
    assert plan_file_groups(diff, min_files=5).enabled is True
    assert plan_file_groups(diff, min_diff_lines=50).enabled is True
    assert plan_file_groups(diff, min_files=6, min_diff_lines=51).enabled is False


# --------------------------------------------------------------------------- concurrency


class _OverlapProbe:
    """Async dispatcher that records start/finish order and peak overlap."""

    def __init__(self, *, delay_s: float = 0.02, fail_group: str | None = None) -> None:
        self.delay_s = delay_s
        self.fail_group = fail_group
        self.events: list[tuple[str, str]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def __call__(self, group: FileGroup) -> str:
        self.events.append(("start", group.group_id))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(self.delay_s)
            if group.group_id == self.fail_group:
                raise RuntimeError("provider unavailable")
            return f"ok:{group.group_id}"
        finally:
            self.in_flight -= 1
            self.events.append(("finish", group.group_id))


def _sequential_events(group_count: int) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []
    for index in range(1, group_count + 1):
        events.extend([("start", f"group-{index}"), ("finish", f"group-{index}")])
    return events


def test_dispatch_is_sequential_by_default() -> None:
    """``concurrency`` defaults to 1: each group finishes before the next starts."""
    plan = plan_file_groups(_diff(30, 30), max_groups=4)
    probe = _OverlapProbe()

    summary = asyncio.run(dispatch_file_groups(plan, probe))

    assert probe.events == _sequential_events(4)
    assert probe.max_in_flight == 1
    assert summary.results == ("ok:group-1", "ok:group-2", "ok:group-3", "ok:group-4")


def test_concurrency_one_is_strictly_sequential() -> None:
    plan = plan_file_groups(_diff(30, 30), max_groups=3)
    probe = _OverlapProbe()

    asyncio.run(dispatch_file_groups(plan, probe, concurrency=1))

    assert probe.events == _sequential_events(3)
    assert probe.max_in_flight == 1


@pytest.mark.parametrize(("concurrency", "peak"), [(2, 2), (3, 3), (6, 6), (12, 6)])
def test_concurrency_bounds_groups_in_flight(concurrency: int, peak: int) -> None:
    plan = plan_file_groups(_diff(40, 25), max_groups=6)
    probe = _OverlapProbe(delay_s=0.05)

    summary = asyncio.run(dispatch_file_groups(plan, probe, concurrency=concurrency))

    assert probe.max_in_flight == peak
    assert len(summary.results) == 6


def test_concurrent_dispatch_still_degrades_a_failed_group_in_plan_order() -> None:
    plan = plan_file_groups(_diff(40, 25), max_groups=4)
    probe = _OverlapProbe(delay_s=0.02, fail_group="group-3")
    recorded: list[tuple[str, str]] = []

    summary = asyncio.run(
        dispatch_file_groups(
            plan,
            probe,
            concurrency=2,
            on_failure=lambda gid, why: recorded.append((gid, why)),
        )
    )

    assert probe.max_in_flight == 2
    assert summary.degraded is True
    assert summary.failures == (("group-3", "provider unavailable"),)
    assert recorded == [("group-3", "provider unavailable")]
    assert summary.results == ("ok:group-1", "ok:group-2", "ok:group-4")
