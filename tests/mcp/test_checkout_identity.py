"""A moving pull ref must not attach a review to another revision."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_checkout import _ctx_for, _git, _pr_repo_with_two_commits, _StubGitHub

from mergecraft.mcp.checkout import checkout_pr_tool
from mergecraft.mcp.tool_state import primary_repo_state

if TYPE_CHECKING:
    from pathlib import Path


class _OfflineGitHub(_StubGitHub):
    async def get(self, path: str, **kwargs: Any) -> Any:
        return [] if path.endswith("/files") else {}


@pytest.mark.asyncio
async def test_checkout_ref_moving_after_api_lookup_is_refused(tmp_path: Path) -> None:
    repo, advertised, _fetched = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
    await asyncio.to_thread(_git, repo, "checkout", "base")
    ctx = _ctx_for(
        repo,
        _OfflineGitHub(head_sha=advertised, reviews=[]),
        tmp_path,
        mode="Review",
        analyzers_mode="off",
    )

    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})

    assert result.is_error, result.content
    assert "head changed" in str(result.content)
    assert primary_repo_state(ctx.tool_state).checkout_sha is None
    assert ctx.tool_state.scope_provenance is None
    assert not await asyncio.to_thread((repo / "new.py").exists)


@pytest.mark.asyncio
@pytest.mark.parametrize("missing_api_sha", [False, True])
async def test_checkout_records_the_verified_commit(tmp_path: Path, missing_api_sha: bool) -> None:
    repo, _first, fetched = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)
    ctx = _ctx_for(
        repo,
        _OfflineGitHub(head_sha="" if missing_api_sha else fetched, reviews=[]),
        tmp_path,
        mode="Review",
        analyzers_mode="off",
    )

    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})

    assert not result.is_error, result.content
    payload = json.loads(result.content[0]["text"])
    assert payload["headSha"] == fetched
    assert primary_repo_state(ctx.tool_state).checkout_sha == fetched
    assert ctx.tool_state.scope_provenance == "checkout"


@pytest.mark.asyncio
@pytest.mark.parametrize("head_fetch_fails", [False, True])
async def test_files_api_cannot_rebind_to_a_new_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, head_fetch_fails: bool
) -> None:
    from mergecraft.mcp import checkout as checkout_module

    repo, previous, fetched = await asyncio.to_thread(_pr_repo_with_two_commits, tmp_path)

    class MovingGitHub(_OfflineGitHub):
        async def get(self, path: str, **kwargs: Any) -> Any:
            if path.endswith("/files"):
                self._head_sha = previous
                return []
            return await super().get(path, **kwargs)

    if head_fetch_fails:
        monkeypatch.setattr(
            checkout_module, "_fetch_head_with_retry", lambda **kw: (False, "offline")
        )
    else:
        real_git = checkout_module._run_git

        def fail_diff(args: list[str], **kwargs: Any) -> str:
            if args[:2] == ["diff", "--merge-base"]:
                raise RuntimeError("unavailable base")
            return real_git(args, **kwargs)

        monkeypatch.setattr(checkout_module, "_run_git", fail_diff)
    ctx = _ctx_for(
        repo,
        MovingGitHub(head_sha=fetched, reviews=[]),
        tmp_path,
        mode="Review",
        analyzers_mode="off",
    )

    result = await checkout_pr_tool(ctx).execute({"pull_number": 1})

    assert result.is_error, result.content
    assert "head changed" in str(result.content)
    assert ctx.tool_state.scope_provenance is None
