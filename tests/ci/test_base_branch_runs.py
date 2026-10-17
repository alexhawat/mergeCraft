"""``analyze_ci_failures`` reads the base branch's runs itself (#891).

A same-fingerprint *failing* base run clears a failure as pre-existing with no
agent-supplied arguments; a passing or unrecognised base never clears.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

import pytest

from mergecraft.ci.intelligence import run_ci_intelligence
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.scm.types import ListedItems
from mergecraft.utils.github import GitHubClient

HEAD_SHA = "cafebabecafebabecafebabecafebabecafebabe"
BASE_SHA = "b4s3b4s3b4s3b4s3b4s3b4s3b4s3b4s3b4s3b4s3"

_FAILING_LOG = (
    "2026-10-01T10:00:00.0000000Z ##[group]Run make test\n"
    "2026-10-01T10:00:01.0000000Z FAILED tests/test_billing.py::test_total - AssertionError\n"
    "2026-10-01T10:00:02.0000000Z ##[error]Process completed with exit code 2.\n"
)
_OTHER_LOG = (
    "2026-10-01T10:00:00.0000000Z ##[group]Run make lint\n"
    "2026-10-01T10:00:01.0000000Z Error: unrelated lint explosion in tools/gen.py\n"
    "2026-10-01T10:00:02.0000000Z ##[error]Process completed with exit code 1.\n"
)


def _zip(log: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("1_job.txt", log)
    return buffer.getvalue()


class _Github(GitHubClient):
    """Serves a failing PR-head run and a configurable list of base-branch runs."""

    def __init__(
        self,
        *,
        base_runs: list[dict[str, Any]],
        base_logs: dict[int, str],
        head_log: str = _FAILING_LOG,
        branch_error: Exception | None = None,
    ) -> None:
        super().__init__(token="test-token")
        self.base_runs = base_runs
        self.base_logs = base_logs
        self.head_log = head_log
        self.branch_error = branch_error
        self.branch_queries: list[str] = []
        self.log_downloads: list[int] = []

    async def list_workflow_runs_for_check_suite(self, owner: str, repo: str, check_suite_id: int):
        _ = (owner, repo, check_suite_id)
        return ListedItems(
            items=[
                {
                    "id": 1,
                    "name": "CI",
                    "workflow_id": 11,
                    "conclusion": "failure",
                    "head_sha": HEAD_SHA,
                    "html_url": "https://example.test/run/1",
                }
            ],
            incomplete=False,
        )

    async def list_workflow_runs_for_branch(
        self, owner: str, repo: str, branch: str, **kwargs: Any
    ) -> ListedItems:
        _ = (owner, repo, kwargs)
        self.branch_queries.append(branch)
        if self.branch_error is not None:
            raise self.branch_error
        return ListedItems(items=list(self.base_runs), incomplete=False)

    async def download_workflow_run_logs(self, owner: str, repo: str, run_id: int) -> bytes:
        _ = (owner, repo)
        self.log_downloads.append(run_id)
        if run_id == 1:
            return _zip(self.head_log)
        return _zip(self.base_logs[run_id])

    async def list_check_runs_for_ref(self, owner: str, repo: str, ref: str, **kwargs: Any):
        _ = (owner, repo, ref, kwargs)
        return ListedItems(items=[], incomplete=False, total_count=0)


def _base_run(run_id: int, conclusion: str, *, workflow_id: int = 11) -> dict[str, Any]:
    return {
        "id": run_id,
        "name": "CI",
        "workflow_id": workflow_id,
        "conclusion": conclusion,
        "status": "completed",
        "head_sha": BASE_SHA,
        "head_branch": "main",
        "html_url": f"https://example.test/run/{run_id}",
    }


def _ctx(tmp_path: Path, github: GitHubClient, *, with_base: bool = True) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    primary_repo_state(state).checkout_sha = HEAD_SHA
    event = (
        {"pull_request": {"number": 7, "base": {"ref": "main", "sha": BASE_SHA}}}
        if with_base
        else None
    )
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
        gh_event=event,
    )


@pytest.mark.asyncio
async def test_matching_failing_base_run_clears_the_failure_with_no_agent_arguments(
    tmp_path: Path,
) -> None:
    github = _Github(
        base_runs=[_base_run(100, "failure"), _base_run(99, "success")],
        base_logs={100: _FAILING_LOG, 99: ""},
    )
    ctx = _ctx(tmp_path, github)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert github.branch_queries == ["main"]
    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["probably_not_this_pr"]
    assert payload["stats"]["unattributedCount"] == 0
    assert payload["stats"]["prAttributedCount"] == 0


@pytest.mark.asyncio
async def test_the_base_runs_used_appear_in_the_recorded_evidence(tmp_path: Path) -> None:
    github = _Github(base_runs=[_base_run(100, "failure")], base_logs={100: _FAILING_LOG})
    ctx = _ctx(tmp_path, github)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    used = payload["baseBranchRuns"]
    assert len(used) == 1
    assert used[0]["conclusion"] == "failure"
    assert used[0]["run_id"] == 100
    assert used[0]["ref"].startswith("main")
    assert used[0]["fingerprint"] == payload["clusters"][0]["fingerprint"]
    assert ctx.tool_state.ci_evidence is not None
    assert ctx.tool_state.ci_evidence.base_branch_runs == used


@pytest.mark.asyncio
@pytest.mark.parametrize("conclusion", ["success", "cancelled", "neutral", "skipped", "stale"])
async def test_a_passing_or_unrecognised_base_status_never_clears(
    tmp_path: Path, conclusion: str
) -> None:
    github = _Github(base_runs=[_base_run(100, conclusion)], base_logs={100: ""})
    ctx = _ctx(tmp_path, github)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]
    assert payload["stats"]["unattributedCount"] == 1


@pytest.mark.asyncio
async def test_a_base_failure_with_a_different_fingerprint_does_not_clear(tmp_path: Path) -> None:
    github = _Github(base_runs=[_base_run(100, "failure")], base_logs={100: _OTHER_LOG})
    ctx = _ctx(tmp_path, github)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]


@pytest.mark.asyncio
async def test_a_base_failure_in_another_workflow_is_not_consulted(tmp_path: Path) -> None:
    github = _Github(
        base_runs=[_base_run(100, "failure", workflow_id=99)], base_logs={100: _FAILING_LOG}
    )
    ctx = _ctx(tmp_path, github)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]
    assert 100 not in github.log_downloads


@pytest.mark.asyncio
async def test_cleared_failure_stays_recorded_but_does_not_block_the_packet(tmp_path: Path) -> None:
    from mergecraft.ci.evidence import ci_evidence_findings

    github = _Github(base_runs=[_base_run(100, "failure")], base_logs={100: _FAILING_LOG})
    ctx = _ctx(tmp_path, github)

    await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    recorded = ci_evidence_findings(ctx.tool_state)
    assert [finding.introduced_by_pr for finding in recorded] == ["false"]
    assert [finding.severity for finding in recorded] == ["Minor"]


@pytest.mark.asyncio
async def test_listing_failure_degrades_to_the_unattributed_report(tmp_path: Path) -> None:
    github = _Github(base_runs=[], base_logs={}, branch_error=RuntimeError("rate limited"))
    ctx = _ctx(tmp_path, github)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]
    assert payload["baseBranchRuns"] == []
    assert payload.get("baseBranchRunsNote")


@pytest.mark.asyncio
async def test_no_base_branch_in_the_event_makes_no_api_call(tmp_path: Path) -> None:
    github = _Github(base_runs=[_base_run(100, "failure")], base_logs={100: _FAILING_LOG})
    ctx = _ctx(tmp_path, github, with_base=False)

    payload = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])

    assert github.branch_queries == []
    assert payload["baseBranchRuns"] == []
    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["unknown"]


@pytest.mark.asyncio
async def test_agent_supplied_runs_are_still_honoured_alongside_the_producer(
    tmp_path: Path,
) -> None:
    github = _Github(base_runs=[], base_logs={})
    ctx = _ctx(tmp_path, github)
    first = await run_ci_intelligence(ctx, check_suite_id=9, pr_diff_paths=["README.md"])
    fingerprint = first["clusters"][0]["fingerprint"]

    ctx = _ctx(tmp_path, _Github(base_runs=[], base_logs={}))
    payload = await run_ci_intelligence(
        ctx,
        check_suite_id=9,
        pr_diff_paths=["README.md"],
        base_branch_runs=[{"ref": "main", "conclusion": "failure", "fingerprint": fingerprint}],
    )

    assert [cluster["blameVerdict"] for cluster in payload["clusters"]] == ["probably_not_this_pr"]
