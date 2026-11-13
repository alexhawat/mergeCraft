"""The Action checkout enforces the same file-wise diff bound as offline review."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from tests.mcp.test_checkout_degraded_diff import (
    _checkout,
    _ctx_for,
    _fail_merge_base_diff,
    _StubGitHub,
)
from tests.mcp.test_checkout_ignore_paths import _mixed_pr_repo

from mergecraft.config.settings import RepoSettings
from mergecraft.evidence.coverage import coverage_section_for_state
from mergecraft.main import _coverage_gate_reason
from mergecraft.utils.run_bounds import BudgetTracker, resolve_run_bounds


@pytest.mark.parametrize("api_fallback", [False, True], ids=["git", "files-api"])
async def test_checkout_bounds_diff_and_cannot_treat_omitted_files_as_reviewed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, api_fallback: bool
) -> None:
    repo = _mixed_pr_repo(tmp_path)
    pages = {
        1: [
            {
                "filename": name,
                "status": "modified",
                "additions": 1,
                "deletions": 1,
                "patch": "@@ -1 +1 @@\n-old\n+new",
            }
            for name in ("a.py", "b.py", "c.py")
        ]
    }
    ctx = _ctx_for(repo, _StubGitHub(pages=pages), tmp_path)
    settings = RepoSettings.model_validate({"runBounds": {"maxDiffLines": 8}})
    ctx.budget_tracker = BudgetTracker(resolve_run_bounds(settings=settings, env={}))
    if api_fallback:
        _fail_merge_base_diff(monkeypatch)

    is_error, payload = await _checkout(ctx)

    assert not is_error
    assert isinstance(payload, dict)
    diff = await asyncio.to_thread(Path(payload["diffPath"]).read_text)
    assert len(diff.splitlines()) <= 8
    assert payload["unreviewablePaths"]
    section = coverage_section_for_state(ctx.tool_state)
    assert section is not None
    assert not section.complete
    # Even an advisory coverage policy cannot approve a budget-reduced review.
    assert "max_diff_lines" in (_coverage_gate_reason(ctx, settings) or "")


async def test_incremental_diff_cannot_bypass_the_line_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests.mcp import test_checkout as fixtures

    repo, reviewed_sha, head_sha = fixtures._pr_repo_with_two_commits(tmp_path)
    fixtures._pin_publishers(monkeypatch, frozenset({fixtures._PUBLISHER_LOGIN}))
    github = fixtures._StubGitHub(
        head_sha=head_sha,
        reviews=[
            {
                "commit_id": reviewed_sha,
                "body": fixtures._MERGECRAFT_BODY,
                "user": fixtures._BOT_USER,
            }
        ],
    )
    ctx = fixtures._ctx_for(repo, github, tmp_path, mode="IncrementalReview")
    settings = RepoSettings.model_validate({"runBounds": {"maxDiffLines": 1}})
    ctx.budget_tracker = BudgetTracker(resolve_run_bounds(settings=settings, env={}))

    payload = await fixtures._checkout(ctx)

    diff = await asyncio.to_thread(Path(payload["incrementalDiffPath"]).read_text)
    assert diff == "", "a whole file exceeding the limit must be omitted, not sliced"
    assert "new.py" in payload["unreviewablePaths"]
    assert "max_diff_lines" in (_coverage_gate_reason(ctx, settings) or "")
