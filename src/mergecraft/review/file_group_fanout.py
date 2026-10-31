"""File-group planner for read-only reviewer fan-out (slice 5).

A very large diff is where one reviewer spends its budget reading files
serially. The safe shape is a bounded set of read-only groups, each given a
slice of the changed files plus the same materialised diff path, with findings
aggregated afterwards. This module is the *planning and degradation* half:

* :func:`plan_file_groups` turns a diff TOC into at most ``max_groups`` balanced
  groups, and returns no groups below the size threshold.
* :func:`dispatch_file_groups` runs a caller-supplied async dispatcher with
  ``return_exceptions`` semantics, so one failed group becomes a recorded
  finding instead of a failed review.

The server-side roster dispatch (``review/roster_execution.py``) remains the
only path that actually spawns reviewer agents today. Wiring this planner into
that path is deliberately not part of slice 5: it needs live-provider
validation of group prompts and aggregation, so it is filed as a follow-up
rather than switched on unverified. Nothing here can fail a run: it returns a
summary.

Module: mergecraft.review.file_group_fanout
Depends: mergecraft.evidence.diff_coverage, loguru

Exports:
    FileGroup — One read-only reviewer's file slice.
    FanoutPlan — Bounded groups plus why the plan has that shape.
    FanoutSummary — Per-group outcomes and recorded failures.
    plan_file_groups — Build a bounded plan from a unified diff.
    dispatch_file_groups — Run the dispatcher, degrading failures.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.evidence.diff_coverage import parse_diff_toc

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

DEFAULT_MAX_GROUPS: Final[int] = 6
DEFAULT_MIN_DIFF_LINES: Final[int] = 800
DEFAULT_MIN_FILES: Final[int] = 20
"""Fan-out is for genuinely large PRs, not for every multi-file change."""


@dataclass(frozen=True, slots=True)
class FileGroup:
    """One read-only reviewer's slice of the changed files."""

    group_id: str
    paths: tuple[str, ...]
    diff_lines: int


@dataclass(frozen=True, slots=True)
class FanoutPlan:
    """Bounded file groups plus the reason for the plan's shape."""

    groups: tuple[FileGroup, ...]
    reason: str

    @property
    def enabled(self) -> bool:
        """Return whether the plan fans out at all."""
        return bool(self.groups)


@dataclass(frozen=True, slots=True)
class FanoutSummary:
    """Outcome of dispatching one plan.

    ``failures`` are ``(group_id, reason)`` rows the caller records as findings
    or run-health notes. A failed group never propagates as an exception.
    """

    results: tuple[Any, ...] = ()
    failures: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def degraded(self) -> bool:
        """Return whether any group failed."""
        return bool(self.failures)


def plan_file_groups(
    diff_text: str,
    *,
    max_groups: int = DEFAULT_MAX_GROUPS,
    min_diff_lines: int = DEFAULT_MIN_DIFF_LINES,
    min_files: int = DEFAULT_MIN_FILES,
) -> FanoutPlan:
    """Plan bounded read-only groups from the diff's added-line TOC.

    Below the threshold the single-agent path is cheaper and better: the
    primary reviewer already holds the whole scope, and extra dispatches add
    round-trips without dividing real work. Above it, files are packed
    largest-first into the emptiest group so each reviewer gets a comparable
    slice and the group count never exceeds ``max_groups``.
    """
    entries = parse_diff_toc(diff_text)
    if not entries:
        return FanoutPlan(groups=(), reason="the diff has no added lines to review")
    total_lines = sum(entry.line_count for entry in entries)
    if len(entries) < min_files and total_lines < min_diff_lines:
        return FanoutPlan(
            groups=(),
            reason=(
                f"diff is below the fan-out threshold ({len(entries)} files, "
                f"{total_lines} added lines)"
            ),
        )
    group_count = max(1, min(int(max_groups), len(entries)))
    buckets: list[list[Any]] = [[] for _ in range(group_count)]
    loads = [0] * group_count
    for entry in sorted(entries, key=lambda item: item.line_count, reverse=True):
        target = min(range(group_count), key=lambda index: loads[index])
        buckets[target].append(entry)
        loads[target] += entry.line_count
    groups = tuple(
        FileGroup(
            group_id=f"group-{index + 1}",
            paths=tuple(entry.path for entry in sorted(bucket, key=lambda item: item.path)),
            diff_lines=loads[index],
        )
        for index, bucket in enumerate(buckets)
        if bucket
    )
    return FanoutPlan(
        groups=groups,
        reason=(
            f"{len(entries)} files / {total_lines} added lines split into "
            f"{len(groups)} bounded read-only group(s)"
        ),
    )


async def dispatch_file_groups(
    plan: FanoutPlan,
    dispatch: Callable[[FileGroup], Awaitable[Any]],
    *,
    on_failure: Callable[[str, str], None] | None = None,
) -> FanoutSummary:
    """Dispatch every group; a failed group is recorded, never re-raised.

    Args:
        plan: The bounded plan from :func:`plan_file_groups`.
        dispatch: Async callable that runs one read-only reviewer for a group.
        on_failure: Optional recorder for ``(group_id, reason)`` rows. The
            summary carries the same rows either way.

    Returns:
        A :class:`FanoutSummary`. A run with no groups returns an empty summary
        without calling ``dispatch``.
    """
    if not plan.groups:
        return FanoutSummary()
    outcomes: list[Any] = []
    failures: list[tuple[str, str]] = []
    results = await asyncio.gather(
        *(dispatch(group) for group in plan.groups),
        return_exceptions=True,
    )
    for group, result in zip(plan.groups, results, strict=True):
        if isinstance(result, BaseException):
            reason = str(result) or result.__class__.__name__
            failures.append((group.group_id, reason))
            logger.warning("file-group fan-out {} failed: {}", group.group_id, reason)
            if on_failure is not None:
                try:
                    on_failure(group.group_id, reason)
                except Exception as recorder_error:
                    logger.warning(
                        "file-group fan-out failure recorder raised for {}: {}",
                        group.group_id,
                        recorder_error,
                    )
            continue
        outcomes.append(result)
    return FanoutSummary(results=tuple(outcomes), failures=tuple(failures))


__all__ = [
    "DEFAULT_MAX_GROUPS",
    "DEFAULT_MIN_DIFF_LINES",
    "DEFAULT_MIN_FILES",
    "FanoutPlan",
    "FanoutSummary",
    "FileGroup",
    "dispatch_file_groups",
    "plan_file_groups",
]
