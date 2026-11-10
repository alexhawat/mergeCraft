"""#1245 - issue read tools must not rebind the run's issue/PR number."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

from tests.support.tool_context import make_tool_context

from mergecraft.mcp.comment import report_progress_tool
from mergecraft.mcp.issue_comments import get_issue_comments_tool
from mergecraft.mcp.issue_events import get_issue_events_tool
from mergecraft.mcp.issue_info import get_issue_tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext

_BOUND = 7
_READ = 99


def _scm() -> MagicMock:
    scm = MagicMock()
    scm.get_issue = AsyncMock(return_value={"number": _READ, "comments": 0, "labels": []})
    scm.get = AsyncMock(return_value=[])
    scm.list_issue_comments = AsyncMock(return_value=[])
    scm.create_issue_comment = AsyncMock(return_value={"id": 5})
    scm.update_issue_comment = AsyncMock(return_value={"id": 5})
    scm.list_issue_comments_for_sticky = AsyncMock(return_value=[])
    return scm


def _ctx(tmp_path: Path, scm: MagicMock) -> ToolContext:
    ctx = make_tool_context(tmp_path, trust_tier="trusted", scm=scm)
    primary_repo_state(ctx.tool_state).issue_number = _BOUND
    return ctx


async def _read_all(ctx: ToolContext) -> None:
    for factory in (get_issue_tool, get_issue_comments_tool, get_issue_events_tool):
        result = await factory(ctx).execute({"issue_number": _READ})
        assert result.is_error is False, result.content[0]["text"]


async def test_readers_leave_bound_issue_number_untouched(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, _scm())
    await _read_all(ctx)
    assert primary_repo_state(ctx.tool_state).issue_number == _BOUND


async def test_readers_do_not_bind_when_nothing_was_bound(tmp_path: Path) -> None:
    ctx = make_tool_context(tmp_path, trust_tier="trusted", scm=_scm())
    assert primary_repo_state(ctx.tool_state).issue_number is None
    await _read_all(ctx)
    assert primary_repo_state(ctx.tool_state).issue_number is None


async def test_progress_after_reading_another_issue_targets_the_bound_one(
    tmp_path: Path,
) -> None:
    scm = _scm()
    ctx = _ctx(tmp_path, scm)
    ctx.tool_state.selected_mode = None
    await _read_all(ctx)

    result = await report_progress_tool(ctx).execute({"body": "hello"})
    assert result.is_error is False, result.content[0]["text"]

    payload: dict[str, Any] = json.loads(result.content[0]["text"])
    assert payload["success"] is True
    touched = [call.args[2] for call in scm.create_issue_comment.await_args_list]
    assert touched == [_BOUND]
    assert _READ not in touched
