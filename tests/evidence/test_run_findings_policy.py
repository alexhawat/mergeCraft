"""Policy rows reach the packet and the approval check exactly once.

``load_run_findings_with_drops`` is the one loader the merge-evidence packet and
the ``mergecraft-approval`` check share. A server-computed policy population
joins it the way CI evidence already does: after the drop filter, deduplicated
by fingerprint, and invisible to the agent's ``drop`` valve.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, report_status_checks
from tests.support.policy_fixtures import row_text, rule, write_diff, write_policy

if TYPE_CHECKING:
    from pathlib import Path

_PR_HEAD_SHA = "aaa1111111111111111111111111111111111111111"
_BILLING_SCOPE = {"path": "src/billing/**"}


class _RecordingGitHub(GitHubClient):
    """Records the check-runs the gate posts."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.check_runs: list[dict[str, Any]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"head": {"sha": _PR_HEAD_SHA}}

    async def post(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/check-runs"):
            body = kwargs.get("json")
            if isinstance(body, dict):
                self.check_runs.append(body)
        return {}


def _ctx(tmp_path: Path, *, github: GitHubClient) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.pr_number = 7
    primary_repo_state(tool_state).issue_number = 7
    primary_repo_state(tool_state).checkout_sha = _PR_HEAD_SHA
    primary_repo_state(tool_state).diff_path = str(write_diff(tmp_path, "src/billing/x.py"))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            status_checks=True,
            shell="restricted",
        ),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=tool_state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )


def _policy_ctx(tmp_path: Path, *, github: GitHubClient | None = None) -> ToolContext:
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope=_BILLING_SCOPE)])
    return _ctx(tmp_path, github=github or _RecordingGitHub())


def test_the_policy_row_reaches_the_gate_loader_exactly_once(tmp_path: Path) -> None:
    """One merged population, deduplicated on the fingerprint."""
    from mergecraft.evidence.findings import load_run_findings_with_drops

    ctx = _policy_ctx(tmp_path)

    findings, dropped = load_run_findings_with_drops(ctx)

    matching = [row for row in findings if row.rule_id == "billing.no-secret"]
    assert len(matching) == 1
    assert dropped == 0
    assert matching[0].tool == "policy"


@pytest.mark.asyncio
async def test_backfill_does_not_duplicate_the_policy_row_into_agent_findings(
    tmp_path: Path,
) -> None:
    """A policy row is not an agent claim, so the backfill leaves it alone."""
    from mergecraft.policy.review import ensure_policy_evaluated

    from mergecraft.evidence.findings import load_run_findings_with_drops
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    ctx = _policy_ctx(tmp_path)
    rows = ensure_policy_evaluated(ctx)
    assert len(rows) == 1
    fingerprint = rows[0].fingerprint

    result = await submit_review_verdict_tool(ctx).execute(
        {"verdict": "approve", "summary": "LGTM", "findings": []}
    )
    assert result.is_error is False, result.content[0]["text"]
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    assert submission.verdict == "request_changes"

    stored = {
        str(row.get("fingerprint"))
        for row in ctx.tool_state.agent_findings
        if isinstance(row, dict)
    }
    assert fingerprint not in stored, "the backfill must not store a policy row as an agent row"

    findings, _dropped = load_run_findings_with_drops(ctx)
    assert len([row for row in findings if row.fingerprint == fingerprint]) == 1


@pytest.mark.asyncio
async def test_the_packet_decision_and_the_approval_check_both_fail(tmp_path: Path) -> None:
    """``decide_approval`` reads the policy row, and the check follows it."""
    from mergecraft.agents.gates import decide_approval
    from mergecraft.evidence.run_packet import prepare_run_packet

    github = _RecordingGitHub()
    ctx = _policy_ctx(tmp_path, github=github)

    packet = prepare_run_packet(ctx, run_succeeded=True)
    assert packet is not None
    assert any(row.tool == "policy" for row in packet.findings)
    policy_row = next(row for row in packet.findings if row.rule_id == "billing.no-secret")
    assert "sha256:" in row_text(policy_row)

    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure"
    assert packet.decision is not None
    assert packet.decision.verdict == "failure"

    await report_status_checks(ctx, run_succeeded=True, packet=packet)

    approval = [run for run in github.check_runs if run.get("name") == APPROVAL_CHECK]
    assert approval, f"expected a {APPROVAL_CHECK} check-run, got {github.check_runs!r}"
    assert approval[0]["conclusion"] == "failure"
