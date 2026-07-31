"""Regression tests for learnings persistence honesty (issue #7 / D7)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from loguru import logger

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.learnings import (
    ensure_learnings_review_delta,
    merge_learnings_delta_into_review_body,
    persist_learnings,
    seed_learnings_file,
)

if TYPE_CHECKING:
    from _pytest.monkeypatch import MonkeyPatch


def _ctx(
    tmp_path: Path,
    *,
    learnings_file_path: str,
    learnings_seed: str,
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.learnings_file_path = learnings_file_path
    tool_state.learnings_seed = learnings_seed
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request", is_pr=True)),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


@pytest.mark.asyncio
async def test_persist_learnings_warns_ephemeral_and_surfaces_delta(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Ephemeral GITHUB_WORKSPACE persist must warn (not info-success) and expose the delta."""
    workspace = tmp_path / "runner-workspace"
    workspace.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))

    seed = "# Learnings\n\n## Build\n- keep this\n"
    delta_line = "- reviewer added this during the run\n"
    updated = seed + f"\n## Review memory\n{delta_line}"

    learnings_path = await seed_learnings_file(tmpdir=str(tmp_path / "agent-tmp"), current=updated)
    ctx = _ctx(tmp_path, learnings_file_path=learnings_path, learnings_seed=seed)

    log_records: list[tuple[str, str]] = []

    def _capture(record: object) -> None:
        entry = record.record  # type: ignore[attr-defined]
        log_records.append((entry["level"].name, entry["message"]))

    sink_id = logger.add(_capture, level="DEBUG")
    try:
        await persist_learnings(ctx)
    finally:
        logger.remove(sink_id)

    info_success = [
        message
        for level, message in log_records
        if level == "INFO" and "learnings updated" in message.lower()
    ]
    assert not info_success, "ephemeral persist must not log info-level success"

    warnings = [message for level, message in log_records if level == "WARNING"]
    assert warnings
    joined = " ".join(warnings).lower()
    assert "ephemeral" in joined or "will not survive" in joined or "not survive" in joined

    delta = getattr(ctx.tool_state, "learnings_review_delta", None)
    assert delta is not None
    assert delta.strip()
    assert delta_line.strip() in delta or "## Review memory" in delta


@pytest.mark.asyncio
async def test_ensure_learnings_review_delta_before_persist(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Review/comment paths can surface the delta before post-run persist_learnings."""
    workspace = tmp_path / "runner-workspace"
    workspace.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))

    seed = "# Learnings\n\n## Build\n- keep this\n"
    delta_line = "- reviewer added this during the run\n"
    updated = seed + f"\n## Review memory\n{delta_line}"

    learnings_path = await seed_learnings_file(tmpdir=str(tmp_path / "agent-tmp"), current=updated)
    ctx = _ctx(tmp_path, learnings_file_path=learnings_path, learnings_seed=seed)

    await ensure_learnings_review_delta(ctx.tool_state)
    body = merge_learnings_delta_into_review_body(ctx.tool_state, "## Review\n\nLooks good.")
    assert "### Learnings delta" in body
    assert delta_line.strip() in body
    assert ctx.tool_state.learnings_review_delta is not None


@pytest.mark.asyncio
async def test_ensure_learnings_review_delta_refreshes_after_later_edits(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    """Progress and final review must reflect the latest learnings tmpfile contents."""
    workspace = tmp_path / "runner-workspace"
    workspace.mkdir()
    monkeypatch.setenv("GITHUB_WORKSPACE", str(workspace))

    seed = "# Learnings\n\n## Build\n- keep this\n"
    first_edit = seed + "\n## Review memory\n- first edit\n"
    second_edit = first_edit + "\n- second edit\n"

    learnings_path = await seed_learnings_file(
        tmpdir=str(tmp_path / "agent-tmp"), current=first_edit
    )
    ctx = _ctx(tmp_path, learnings_file_path=learnings_path, learnings_seed=seed)

    await ensure_learnings_review_delta(ctx.tool_state)
    first_body = merge_learnings_delta_into_review_body(ctx.tool_state, "progress")
    assert "- first edit" in first_body
    assert "- second edit" not in first_body

    await asyncio.to_thread(Path(learnings_path).write_text, second_edit, encoding="utf-8")
    await ensure_learnings_review_delta(ctx.tool_state)
    second_body = merge_learnings_delta_into_review_body(ctx.tool_state, "review")
    assert "- second edit" in second_body

    stale_progress = merge_learnings_delta_into_review_body(ctx.tool_state, first_body)
    assert "- second edit" in stale_progress
    after_section = stale_progress.split("**After:**", 1)[1]
    assert "- second edit" in after_section
