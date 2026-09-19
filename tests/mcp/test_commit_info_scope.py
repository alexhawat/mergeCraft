"""``get_commit_info`` must not register review scope (RA1.4, N3/D10).

The tool legitimately writes and returns a single-commit patch, but it is a
``REPOSITORY_READ``. Registering that patch as the canonical scope silently
replaces the whole-PR review scope with the last commit's diff, which corrupts
admissible citations, inline anchors and blast radius downstream.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from tests.mcp.support_two_commit_pr import build_two_commit_pr

from mergecraft.mcp.commit_info import get_commit_info_tool
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.mcp.verdict import ReviewPhase, register_review_scope
from mergecraft.modes import compute_modes


def _ctx(pr: Any, tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        scm=pr.scm,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )
    ctx.tool_state.pr_number = pr.pr_number
    primary = primary_repo_state(state)
    primary.checkout_sha = pr.head_sha
    register_review_scope(state, diff_path=str(pr.pr_diff_path), provenance="checkout")
    return ctx


async def _inspect_head(ctx: ToolContext, head_sha: str) -> dict[str, Any]:
    result = await get_commit_info_tool(ctx).execute({"sha": head_sha})
    assert result.is_error is False, result.content[0]["text"]
    import json

    return json.loads(result.content[0]["text"])


def _read_text(path: str) -> str:
    """Sync helper — keeps blocking FS reads out of async test bodies."""
    return Path(path).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_get_commit_info_does_not_change_canonical_scope(tmp_path: Path) -> None:
    pr = build_two_commit_pr(tmp_path)
    ctx = _ctx(pr, tmp_path)
    primary = primary_repo_state(ctx.tool_state)

    await _inspect_head(ctx, pr.head_sha)

    assert primary.diff_path == str(pr.pr_diff_path)
    assert ctx.tool_state.scope_provenance == "checkout"
    assert ctx.tool_state.review_phase == ReviewPhase.ESTABLISH_SCOPE.value


@pytest.mark.asyncio
async def test_get_commit_info_still_returns_a_usable_diff_file(tmp_path: Path) -> None:
    """The tool keeps working: it still writes and returns the commit patch."""
    pr = build_two_commit_pr(tmp_path)
    ctx = _ctx(pr, tmp_path)

    payload = await _inspect_head(ctx, pr.head_sha)

    diff_file = payload.get("diffFile")
    assert diff_file
    text = _read_text(diff_file)
    assert "docs.md" in text


@pytest.mark.asyncio
async def test_admissible_changed_files_survive_head_inspection(tmp_path: Path) -> None:
    from mergecraft.utils.diff_paths import changed_paths_from_diff

    pr = build_two_commit_pr(tmp_path)
    ctx = _ctx(pr, tmp_path)

    await _inspect_head(ctx, pr.head_sha)

    primary = primary_repo_state(ctx.tool_state)
    assert primary.diff_path is not None
    paths = set(changed_paths_from_diff(_read_text(primary.diff_path)))
    assert {"security.py", "docs.md"} <= paths


@pytest.mark.asyncio
async def test_blast_radius_survives_head_inspection(tmp_path: Path) -> None:
    from mergecraft.evidence.run_packet import classify_run_blast_radius

    pr = build_two_commit_pr(tmp_path)
    ctx = _ctx(pr, tmp_path)
    primary = primary_repo_state(ctx.tool_state)
    before = classify_run_blast_radius(pr.pr_diff_text())

    await _inspect_head(ctx, pr.head_sha)

    assert primary.diff_path is not None
    after = classify_run_blast_radius(_read_text(primary.diff_path))
    assert before is not None
    assert after is not None
    assert after.lane == before.lane


@pytest.mark.asyncio
async def test_inline_anchors_survive_head_inspection(tmp_path: Path) -> None:
    from mergecraft.mcp.inline_anchors import build_inline_anchor_index

    pr = build_two_commit_pr(tmp_path)
    ctx = _ctx(pr, tmp_path)

    await _inspect_head(ctx, pr.head_sha)

    primary = primary_repo_state(ctx.tool_state)
    assert primary.diff_path is not None
    index = build_inline_anchor_index(_read_text(primary.diff_path))
    assert any(path == "security.py" for path, _line, _side in index.anchors)
