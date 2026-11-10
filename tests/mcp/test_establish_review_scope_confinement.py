"""``establish_review_scope`` only reads a diff under the checkout or run tmpdir (#1257)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.mcp.test_reviewer_resilience_degraded_scope import (
    _ctx,
    _establish_review_scope_tool,
    _StubGitHub,
)

from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.mcp.verdict import confine_diff_path

if TYPE_CHECKING:
    from pathlib import Path

_HEAD = "1" * 40
_DIFF = "diff --git a/src/a.py b/src/a.py\n"


def _scoped_ctx(tmp_path: Path):
    run_tmp = tmp_path / "run"
    run_tmp.mkdir()
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    ctx = _ctx(repo_dir, _StubGitHub(head_sha=_HEAD))
    ctx.tmpdir = str(run_tmp)
    ctx.tool_state.pr_number = 1
    return ctx, repo_dir, run_tmp


async def _establish(ctx, diff_path: Path | str):
    return await _establish_review_scope_tool(ctx).execute(
        {"diff_path": str(diff_path), "base_sha": "0" * 40, "head_sha": _HEAD}
    )


async def test_diff_under_run_tmpdir_is_accepted(tmp_path: Path) -> None:
    ctx, _repo, run_tmp = _scoped_ctx(tmp_path)
    diff = run_tmp / "pr.diff"
    diff.write_text(_DIFF, encoding="utf-8")
    result = await _establish(ctx, diff)
    assert result.is_error is False, result.content[0]["text"]


async def test_diff_under_checkout_is_accepted(tmp_path: Path) -> None:
    ctx, repo, _run_tmp = _scoped_ctx(tmp_path)
    diff = repo / "pr.diff"
    diff.write_text(_DIFF, encoding="utf-8")
    result = await _establish(ctx, diff)
    assert result.is_error is False, result.content[0]["text"]
    assert primary_repo_state(ctx.tool_state).diff_path == str(diff)


async def test_diff_outside_authorized_roots_is_refused(tmp_path: Path) -> None:
    ctx, _repo, _run_tmp = _scoped_ctx(tmp_path)
    outside = tmp_path / "outside.diff"
    outside.write_text(_DIFF, encoding="utf-8")
    result = await _establish(ctx, outside)
    assert result.is_error is True
    assert "authorized roots" in result.content[0]["text"]
    assert primary_repo_state(ctx.tool_state).diff_path != str(outside)


async def test_dotdot_traversal_is_refused(tmp_path: Path) -> None:
    ctx, _repo, run_tmp = _scoped_ctx(tmp_path)
    (tmp_path / "secret.diff").write_text(_DIFF, encoding="utf-8")
    result = await _establish(ctx, run_tmp / ".." / "secret.diff")
    assert result.is_error is True
    assert "authorized roots" in result.content[0]["text"]


async def test_symlink_escaping_the_tmpdir_is_refused(tmp_path: Path) -> None:
    ctx, _repo, run_tmp = _scoped_ctx(tmp_path)
    target = tmp_path / "secret.diff"
    target.write_text(_DIFF, encoding="utf-8")
    link = run_tmp / "link.diff"
    link.symlink_to(target)
    result = await _establish(ctx, link)
    assert result.is_error is True
    assert "authorized roots" in result.content[0]["text"]


def test_confine_diff_path_honours_merge_craft_temp_dir_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, _repo, _run_tmp = _scoped_ctx(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ValueError, match="authorized roots"):
        confine_diff_path(ctx, str(other / "x.diff"))
    monkeypatch.setenv("MERGECRAFT_TEMP_DIR", str(other))
    assert confine_diff_path(ctx, str(other / "x.diff")) == (other / "x.diff").resolve()
