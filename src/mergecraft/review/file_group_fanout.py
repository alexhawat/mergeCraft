"""File-group planner for read-only reviewer fan-out (slice 5).

A very large diff is where one reviewer spends its budget reading files
serially. The safe shape is a bounded set of read-only groups, each given a
slice of the changed files plus the same materialised diff path, with findings
aggregated afterwards. This module is the *planning and degradation* half:

* :func:`plan_file_groups` turns a diff TOC into at most ``max_groups`` balanced
  groups, and returns no groups when the diff is below **both** size
  thresholds (either one being met triggers the fan-out).
* :func:`dispatch_file_groups` runs a caller-supplied async dispatcher with
  ``return_exceptions`` semantics and at most ``concurrency`` groups in flight,
  so one failed group becomes a recorded finding instead of a failed review.

The server-side roster dispatch
(``review/roster_execution.py::run_file_group_reviewers``) is the only caller
that spawns reviewer agents for these groups, and only when the operator turns
``review.fileGroupFanout`` on. Nothing here can fail a run: it returns a
summary.

Module: mergecraft.review.file_group_fanout
Depends: mergecraft.evidence.diff_coverage, loguru

Exports:
    FILE_GROUP_AGENT_PREFIX — Agent-id prefix of a file-group reviewer run.
    FileGroup — One read-only reviewer's file slice.
    FanoutPlan — Bounded groups plus why the plan has that shape.
    FanoutSummary — Per-group outcomes and recorded failures.
    file_group_agent_id — The ``file-group/<group-id>`` agent id of a group.
    is_file_group_agent_id — Whether an agent id names a file-group run.
    bind_active_file_group — Mark one group's dispatch as in flight.
    active_file_groups — The groups that may be making the current tool call.
    note_file_group_rows — Record which group raised newly stored finding rows.
    file_group_row_owner — The group that raised one finding row, if known.
    plan_file_groups — Build a bounded plan from a unified diff.
    dispatch_file_groups — Run the dispatcher, degrading failures.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from loguru import logger

from mergecraft.evidence.diff_coverage import parse_diff_toc

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Iterator

    from mergecraft.mcp.tool_state import ToolState

DEFAULT_MAX_GROUPS: Final[int] = 6
DEFAULT_MIN_DIFF_LINES: Final[int] = 800
DEFAULT_MIN_FILES: Final[int] = 20
"""Fan-out is for genuinely large PRs, not for every multi-file change."""

FILE_GROUP_AGENT_PREFIX: Final[str] = "file-group/"
"""Agent ids of file-group reviewer runs are ``file-group/<group-id>``."""


def file_group_agent_id(group_id: str) -> str:
    """Return the reviewer agent id recorded for one file group.

    Args:
        group_id: The plan's group id, for example ``group-1``.

    Returns:
        The ``file-group/<group-id>`` agent id.

    Examples:
        >>> file_group_agent_id("group-2")
        'file-group/group-2'
    """
    return f"{FILE_GROUP_AGENT_PREFIX}{group_id}"


def is_file_group_agent_id(agent_id: object) -> bool:
    """Return whether ``agent_id`` names a file-group reviewer run.

    Args:
        agent_id: Any value read from a finding's ``raised_by`` or a run record.

    Returns:
        ``True`` for a string ``file-group/<group-id>`` with a non-empty group id.

    Examples:
        >>> is_file_group_agent_id("file-group/group-1")
        True
        >>> is_file_group_agent_id("reviewer2")
        False
    """
    return (
        isinstance(agent_id, str)
        and agent_id.startswith(FILE_GROUP_AGENT_PREFIX)
        and len(agent_id) > len(FILE_GROUP_AGENT_PREFIX)
    )


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


_ACTIVE_FILE_GROUP: ContextVar[str | None] = ContextVar(
    "mergecraft_active_file_group", default=None
)
"""The group whose dispatch task is running (set per task, so concurrent groups differ)."""


@contextmanager
def bind_active_file_group(tool_state: ToolState, agent_id: str) -> Iterator[None]:
    """Mark ``agent_id`` as an in-flight file group for the duration of the block.

    Two records are kept: a context variable, which reaches tool calls made
    inside this dispatch task (in-process runtimes), and
    ``ToolState.active_file_groups``, which a tool call arriving over the MCP
    HTTP server can read. Both are cleared on exit, including on error.

    Args:
        tool_state: The run's tool state.
        agent_id: The group's ``file-group/<group-id>`` agent id.

    Yields:
        Nothing; the group is active inside the ``with`` block.
    """
    token = _ACTIVE_FILE_GROUP.set(agent_id)
    tool_state.active_file_groups.append(agent_id)
    try:
        yield
    finally:
        _ACTIVE_FILE_GROUP.reset(token)
        if agent_id in tool_state.active_file_groups:
            tool_state.active_file_groups.remove(agent_id)


def active_file_groups(tool_state: ToolState) -> tuple[str, ...]:
    """Return the file groups that may be making the current tool call.

    Inside a group's own dispatch task this is exactly that group. Elsewhere
    (an MCP HTTP request) it is every group in flight: one when groups run
    sequentially, possibly several under ``concurrency`` above 1.

    Args:
        tool_state: The run's tool state.

    Returns:
        The candidate group agent ids; empty outside a fan-out.
    """
    bound = _ACTIVE_FILE_GROUP.get()
    if bound is not None:
        return (bound,)
    return tuple(tool_state.active_file_groups)


def note_file_group_rows(tool_state: ToolState, fingerprints: Iterable[str]) -> None:
    """Record the group that raised newly stored finding rows.

    Only an unambiguous caller is recorded; with several groups in flight and
    no per-task binding, the rows stay unowned and are attributed in
    recording order when a group's run is recorded. The first recorder of a
    fingerprint keeps it.

    Args:
        tool_state: The run's tool state.
        fingerprints: Fingerprints of the rows the current tool call stored.
    """
    candidates = active_file_groups(tool_state)
    if len(candidates) != 1:
        return
    for fingerprint in fingerprints:
        if fingerprint:
            tool_state.file_group_row_owners.setdefault(fingerprint, candidates[0])


def file_group_row_owner(tool_state: ToolState, fingerprint: object) -> str | None:
    """Return the group agent id that raised a finding row, when it is known.

    Args:
        tool_state: The run's tool state.
        fingerprint: The row's fingerprint.

    Returns:
        ``file-group/<group-id>``, or ``None`` for an unowned row.
    """
    if not isinstance(fingerprint, str) or not fingerprint:
        return None
    return tool_state.file_group_row_owners.get(fingerprint)


def plan_file_groups(
    diff_text: str,
    *,
    max_groups: int = DEFAULT_MAX_GROUPS,
    min_diff_lines: int = DEFAULT_MIN_DIFF_LINES,
    min_files: int = DEFAULT_MIN_FILES,
) -> FanoutPlan:
    """Plan bounded read-only groups from the diff's added-line TOC.

    The diff fans out when **either** threshold is met: at least ``min_files``
    changed files, or at least ``min_diff_lines`` added lines. Below both, the
    single-agent path is cheaper and better: the primary reviewer already holds
    the whole scope, and extra dispatches add round-trips without dividing real
    work. Otherwise files are packed largest-first into the emptiest group so
    each reviewer gets a comparable slice and the group count never exceeds
    ``max_groups``.

    Args:
        diff_text: The unified diff to plan from.
        max_groups: Upper bound on the number of groups.
        min_diff_lines: Added-line count that triggers the fan-out on its own.
        min_files: Changed-file count that triggers the fan-out on its own.

    Returns:
        A :class:`FanoutPlan`; its ``groups`` are empty below both thresholds.
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
    concurrency: int = 1,
) -> FanoutSummary:
    """Dispatch every group; a failed group is recorded, never re-raised.

    Args:
        plan: The bounded plan from :func:`plan_file_groups`.
        dispatch: Async callable that runs one read-only reviewer for a group.
        on_failure: Optional recorder for ``(group_id, reason)`` rows, called
            after every group has finished. The summary carries the same rows
            either way.
        concurrency: Most groups in flight at once (values below ``1`` count as
            ``1``). The default ``1`` finishes each group before starting the
            next, in plan order.

    Returns:
        A :class:`FanoutSummary`. A run with no groups returns an empty summary
        without calling ``dispatch``.
    """
    if not plan.groups:
        return FanoutSummary()
    outcomes: list[Any] = []
    failures: list[tuple[str, str]] = []
    limit = asyncio.Semaphore(max(1, int(concurrency)))

    async def _bounded(group: FileGroup) -> Any:
        async with limit:
            return await dispatch(group)

    results = await asyncio.gather(
        *(_bounded(group) for group in plan.groups),
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
    "FILE_GROUP_AGENT_PREFIX",
    "FanoutPlan",
    "FanoutSummary",
    "FileGroup",
    "active_file_groups",
    "bind_active_file_group",
    "dispatch_file_groups",
    "file_group_agent_id",
    "file_group_row_owner",
    "is_file_group_agent_id",
    "note_file_group_rows",
    "plan_file_groups",
]
