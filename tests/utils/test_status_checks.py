"""Regression tests for opt-in commit status checks (issues #5, #6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, report_status_checks

if TYPE_CHECKING:
    from pathlib import Path

PR_HEAD_SHA = "aaa1111111111111111111111111111111111111111"
REVIEWED_SHA = "bbb2222222222222222222222222222222222222222"


class _RecordingGitHub(GitHubClient):
    """Captures check-run POST bodies instead of calling the REST API."""

    def __init__(self, *, pr_head_sha: str = PR_HEAD_SHA) -> None:
        super().__init__(token="test-token")
        self.pr_head_sha = pr_head_sha
        self.check_runs: list[dict[str, Any]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"head": {"sha": self.pr_head_sha}}

    async def post(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/check-runs"):
            body = kwargs.get("json")
            if isinstance(body, dict):
                self.check_runs.append(body)
        return {}


def _ctx(
    tmp_path: Path,
    *,
    github: _RecordingGitHub | None = None,
    approval: ApprovalRecord | None = None,
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.approval = approval
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True),
            status_checks=True,
            shell="restricted",
        ),
        github=github or _RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def _approval_checks(github: _RecordingGitHub) -> list[dict[str, Any]]:
    return [run for run in github.check_runs if run.get("name") == APPROVAL_CHECK]


@pytest.mark.parametrize(
    ("run_succeeded", "approval"),
    [
        (False, None),
        (True, None),
    ],
    ids=["run_failed", "run_ok_no_approval"],
)
@pytest.mark.asyncio
async def test_report_status_checks_posts_neutral_approval_when_review_incomplete(
    tmp_path: Path,
    run_succeeded: bool,
    approval: ApprovalRecord | None,
) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, approval=approval)

    await report_status_checks(ctx, run_succeeded=run_succeeded)

    approval_checks = _approval_checks(github)
    assert len(approval_checks) == 1
    assert approval_checks[0]["conclusion"] == "neutral"
    summary = approval_checks[0]["output"]["summary"]
    assert "did not complete" in summary.lower() or "not complete" in summary.lower()


@pytest.mark.asyncio
async def test_report_status_checks_anchors_approval_to_pr_head_sha(
    tmp_path: Path,
) -> None:
    github = _RecordingGitHub(pr_head_sha=PR_HEAD_SHA)
    ctx = _ctx(
        tmp_path,
        github=github,
        approval=ApprovalRecord(would_approve=True, sha=REVIEWED_SHA),
    )

    await report_status_checks(ctx, run_succeeded=True)

    approval_checks = _approval_checks(github)
    assert len(approval_checks) == 1
    check = approval_checks[0]
    assert check["head_sha"] == PR_HEAD_SHA
    summary = check["output"]["summary"]
    assert REVIEWED_SHA in summary or REVIEWED_SHA[:7] in summary
