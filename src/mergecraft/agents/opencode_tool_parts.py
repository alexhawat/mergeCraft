"""Record completed OpenCode tool parts from both harness transports.

Module: mergecraft.agents.opencode_tool_parts
Depends: mergecraft.evidence.trajectory, mergecraft.mcp.tool_state

Exports:
    record_opencode_part — record a bash or read tool result on the run trajectory.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping

    from mergecraft.mcp.tool_state import ToolState


# The first line of a 2.x ``read`` result that returned text.
_OPENCODE_READ_HEADER_RE: Final[re.Pattern[str]] = re.compile(
    r"^Read file .*, lines (?P<start>\d+)-(?P<end>\d+)$", re.MULTILINE
)


def _record_opencode_bash(tool_state: ToolState | None, part: object) -> None:
    """Record one finished OpenCode ``bash`` tool part on the run's trajectory (#858).

    The part shape is ``{"tool": "bash", "state": {"status", "input": {"command"},
    "output", "metadata": {"exit"}}}`` — in a ``run --format json`` ``tool_use``
    event's ``part`` and in an HTTP turn's ``parts``. Anything else is ignored;
    recording is evidence only and never raises.
    """
    if tool_state is None or not isinstance(part, dict) or part.get("tool") != "bash":
        return
    state = part.get("state")
    if not isinstance(state, dict) or state.get("status") not in {"completed", "error"}:
        return
    tool_input = state.get("input")
    command = tool_input.get("command") if isinstance(tool_input, dict) else None
    metadata = state.get("metadata")
    raw_exit = metadata.get("exit") if isinstance(metadata, dict) else None
    from mergecraft.evidence.trajectory import record_driver_exec

    record_driver_exec(
        tool_state,
        command=command,
        exit_code=raw_exit
        if isinstance(raw_exit, int) and not isinstance(raw_exit, bool)
        else None,
        output=str(state.get("output") or ""),
        failed=state.get("status") == "error",
    )


def _opencode_read_span(state: Mapping[str, object]) -> tuple[int, int] | None:
    """Return the lines a finished ``read`` part showed: see :func:`_record_opencode_read`."""
    from mergecraft.evidence.trajectory import UNKNOWN_READ_SPAN

    output = state.get("output")
    header = _OPENCODE_READ_HEADER_RE.match(output) if isinstance(output, str) else None
    if header is not None:
        return int(header.group("start")), int(header.group("end"))
    metadata = state.get("metadata")
    # 2.x nests the tool's own metadata one level down.
    nested = metadata.get("metadata") if isinstance(metadata, dict) else None
    truncated = any(isinstance(m, dict) and m.get("truncated") for m in (metadata, nested))
    tool_input = state.get("input")
    ranged = isinstance(tool_input, dict) and (
        tool_input.get("offset") is not None or tool_input.get("limit") is not None
    )
    return UNKNOWN_READ_SPAN if truncated or ranged else None


def _record_opencode_read(tool_state: ToolState | None, part: object) -> None:
    """Record one finished OpenCode ``read`` tool part on the run's trajectory.

    The part shape is ``{"tool": "read", "state": {"status", "input", "output",
    "metadata"}}`` — the same two places as ``bash``. ``input`` names the file as
    ``path`` on 2.x and ``filePath`` on 1.x. A byte cap can cut a read short of the
    ``limit`` it asked for, so the lines come from what it showed: 2.x opens its
    output with ``Read file <path>, lines <a>-<b>``. Without that header a read that
    was ranged or truncated showed lines nobody can name, and any other read showed
    the whole file. A failed read showed nothing and is not recorded.
    """
    if tool_state is None or not isinstance(part, dict) or part.get("tool") != "read":
        return
    state = part.get("state")
    if not isinstance(state, dict) or state.get("status") != "completed":
        return
    tool_input = state.get("input")
    if not isinstance(tool_input, dict):
        return
    from mergecraft.evidence.trajectory import record_driver_read

    record_driver_read(
        tool_state,
        path=tool_input.get("path") or tool_input.get("filePath"),
        span=_opencode_read_span(state),
    )


def record_opencode_part(tool_state: ToolState | None, part: object) -> None:
    """Record one OpenCode tool part the trajectory has a door for."""
    _record_opencode_bash(tool_state, part)
    _record_opencode_read(tool_state, part)


__all__ = ["record_opencode_part"]
