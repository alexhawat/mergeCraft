"""RED — review publication bound to run scope (AG2 / MCB-05)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.tool_context import bind_github_client, github_client_from_ctx

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


class _RecordingGitHub(GitHubClient):
    """Capture review payloads and count SCM create_review calls."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.review_payloads: list[dict[str, Any]] = []
        self.create_review_calls: int = 0

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.create_review_calls += 1
        self.review_payloads.append(payload)
        return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}


def _review_ctx(tmp_path: Path, *, pr_number: int = 7) -> ToolContext:
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=_RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )
    bind_github_client(ctx, _RecordingGitHub())
    state = ctx.tool_state
    state.pr_number = pr_number
    state.selected_mode = "Review"
    primary = primary_repo_state(state)
    primary.issue_number = pr_number
    primary.checkout_sha = "deadbeef"
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text("diff --git a/x b/x\n", encoding="utf-8")
    primary.diff_path = str(diff_path)
    return ctx


@pytest.mark.asyncio
async def test_mismatched_pull_number_raises(tmp_path: Path) -> None:
    ctx = _review_ctx(tmp_path, pr_number=7)
    spec = create_pull_request_review_tool(ctx)
    with pytest.raises(ValueError, match=r"PR #8"):
        await spec.execute({"pull_number": 8, "body": "review body", "comments": []})


@pytest.mark.asyncio
async def test_mismatched_pull_number_makes_zero_scm_calls(tmp_path: Path) -> None:
    ctx = _review_ctx(tmp_path, pr_number=7)
    client = github_client_from_ctx(ctx)
    spec = create_pull_request_review_tool(ctx)
    with pytest.raises(ValueError, match=r"PR #8"):
        await spec.execute({"pull_number": 8, "body": "review body", "comments": []})
    assert client.create_review_calls == 0


@pytest.mark.asyncio
async def test_mismatched_pull_number_leaves_issue_number_unchanged(tmp_path: Path) -> None:
    ctx = _review_ctx(tmp_path, pr_number=7)
    primary = primary_repo_state(ctx.tool_state)
    spec = create_pull_request_review_tool(ctx)
    with pytest.raises(ValueError, match=r"PR #8"):
        await spec.execute({"pull_number": 8, "body": "review body", "comments": []})
    assert primary.issue_number == 7


@pytest.mark.asyncio
async def test_mismatched_commit_id_raises(tmp_path: Path) -> None:
    ctx = _review_ctx(tmp_path, pr_number=7)
    spec = create_pull_request_review_tool(ctx)
    with pytest.raises(ValueError, match=r"commit|sha|checkout"):
        await spec.execute(
            {
                "pull_number": 7,
                "body": "review body",
                "comments": [],
                "commit_id": "not-the-checkout-sha",
            }
        )


_MUTATING_REVIEW_TOOLS: tuple[tuple[str, dict[str, Any]], ...] = (
    (
        "create_pull_request_review",
        {"pull_number": 8, "body": "x", "comments": []},
    ),
)


@pytest.mark.asyncio
@pytest.mark.parametrize(("tool_name", "params"), _MUTATING_REVIEW_TOOLS)
async def test_hypothesis_arbitrary_mismatched_targets_never_reach_io(
    tmp_path: Path,
    tool_name: str,
    params: dict[str, Any],
) -> None:
    """Every mutating review tool refuses a PR target that differs from run scope."""
    ctx = _review_ctx(tmp_path, pr_number=7)
    client = github_client_from_ctx(ctx)
    if tool_name == "create_pull_request_review":
        spec = create_pull_request_review_tool(ctx)
        with pytest.raises(ValueError, match=r"PR"):
            await spec.execute(params)
    else:
        pytest.fail(f"unknown mutating review tool {tool_name!r}")
    assert client.create_review_calls == 0
