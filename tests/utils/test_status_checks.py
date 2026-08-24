"""Regression tests for opt-in commit status checks (issues #5, #6, #75).

The approval check conclusion is computed structurally by ``decide_approval``
(``mergecraft.agents.gates``) from the typed ``Finding`` list, the run's
completion state, and the trust tier (D12). Narrative (``ApprovalRecord``) is
never the sole positive input. The pre-W8 "preserve approval when run fails
later" expectation is replaced by the W8 #75 structural contract: a crashed
run yields ``neutral`` (the wire-shape the hardened enforce step blocks on —
D13), regardless of any recorded ``ApprovalRecord.would_approve``. The new
tests below pin that contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.evidence.run_packet import build_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import ApprovalRecord, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, COMPLETION_CHECK, report_status_checks

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
async def test_report_status_checks_neutral_for_crashed_run_with_recorded_approval(
    tmp_path: Path,
) -> None:
    """A recorded ``ApprovalRecord(would_approve=...)`` must not flip a crashed
    run to ``success`` or ``failure`` — D13 fail-closed.

    Replaces the pre-W8 "preserve approval when run fails later" expectation:
    the structural approval gate consults ``decide_approval(findings,
    run_succeeded=False, tier)`` and yields ``"neutral"`` regardless of what
    the agent's boolean recorded. The ``ApprovalRecord`` survives in
    ``tool_state.approval`` as an advisory input for the trajectory / merge-
    evidence work (#41); the reviewed commit SHA is included in the summary
    so operators can audit the run.
    """
    github = _RecordingGitHub()
    ctx = _ctx(
        tmp_path,
        github=github,
        approval=ApprovalRecord(would_approve=False, sha=REVIEWED_SHA),
    )

    await report_status_checks(ctx, run_succeeded=False)

    approval_checks = _approval_checks(github)
    assert len(approval_checks) == 1
    check = approval_checks[0]
    assert check["conclusion"] == "neutral", (
        "W8 / D13 — a crashed run must surface 'neutral' regardless of any "
        "recorded ApprovalRecord; the hardened enforce step blocks on 'neutral'"
    )
    assert (
        REVIEWED_SHA in check["output"]["summary"] or REVIEWED_SHA[:7] in check["output"]["summary"]
    )


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


@pytest.mark.asyncio
async def test_report_status_checks_skips_approval_when_packet_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """build_run_packet failures must not fail the run after completion posted."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    def _boom(*args: object, **kwargs: object) -> None:
        msg = "packet assembly failed"
        raise RuntimeError(msg)

    monkeypatch.setattr("mergecraft.evidence.run_packet.build_run_packet", _boom)
    await report_status_checks(ctx, run_succeeded=True)
    names = [run.get("name") for run in github.check_runs]
    assert COMPLETION_CHECK in names
    assert APPROVAL_CHECK not in names


@pytest.mark.asyncio
async def test_report_status_checks_does_not_rebuild_when_packet_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST uses the prebuilt packet; assembly is not retried for isolation."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    calls = {"n": 0}

    def _boom(*args: object, **kwargs: object) -> None:
        calls["n"] += 1
        msg = "must not rebuild"
        raise RuntimeError(msg)

    monkeypatch.setattr("mergecraft.evidence.run_packet.build_run_packet", _boom)
    await report_status_checks(ctx, run_succeeded=True, packet=packet, packet_ready=True)
    assert calls["n"] == 0
    assert APPROVAL_CHECK in [run.get("name") for run in github.check_runs]


@pytest.mark.asyncio
async def test_report_status_checks_skips_approval_without_rebuilding_failed_packet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    calls = {"n": 0}

    def _boom(*args: object, **kwargs: object) -> None:
        calls["n"] += 1
        msg = "must not rebuild"
        raise RuntimeError(msg)

    monkeypatch.setattr("mergecraft.evidence.run_packet.build_run_packet", _boom)
    await report_status_checks(ctx, run_succeeded=True, packet=None, packet_ready=True)
    assert calls["n"] == 0
    names = [run.get("name") for run in github.check_runs]
    assert COMPLETION_CHECK in names
    assert APPROVAL_CHECK not in names
