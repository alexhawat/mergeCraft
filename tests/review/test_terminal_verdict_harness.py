"""RH4 — terminal verdict via harness replay."""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.agents.shared import AgentResult
from mergecraft.analyzers.finding import make_finding
from mergecraft.main_outcome import _classify_outcome
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.github import GitHubClient
from tests.support.provider_harness.blocks import replay_blocks
from tests.support.provider_harness.schema import load_fixture_file

_FIXTURES = Path(__file__).resolve().parents[1] / "harness" / "fixtures"


@pytest.fixture
def ctx(tmp_path):
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=7, is_pr=True),
            shell="restricted",
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        pr_approve_enabled=True,
    )


def _replay_fixture(name: str, ctx: ToolContext) -> AgentResult:
    fixture = load_fixture_file(_FIXTURES / f"{name}.json")
    replay = replay_blocks(fixture.response.blocks, ctx=ctx)
    return AgentResult(
        success=replay.success,
        output=replay.output,
        error=replay.error,
        terminal_submission_received=replay.terminal_submission_received,
        terminal_submission_id=replay.terminal_submission_id,
    )


def _classify(result: AgentResult) -> RunOutcome:
    outcome, _ = _classify_outcome(
        result=result,
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode="Review",
    )
    return outcome


def test_missing_terminal_submission_from_replay_is_inconclusive(ctx) -> None:
    result = _replay_fixture("missing-terminal", ctx)
    assert _classify(result) is RunOutcome.inconclusive


def test_narrative_approval_block_without_submit_cannot_approve(ctx) -> None:
    result = _replay_fixture("narrative-lgtm", ctx)
    assert _classify(result) is RunOutcome.inconclusive


def test_valid_submit_review_verdict_block_keeps_validated_outcome(ctx) -> None:
    result = _replay_fixture("valid-request-changes", ctx)
    assert result.terminal_submission_received is True
    assert result.success is True
    assert _classify(result) is RunOutcome.passed


def test_blocking_finding_submission_reaches_decide_approval(ctx) -> None:
    result = _replay_fixture("valid-request-changes", ctx)
    assert result.terminal_submission_received is True
    blocker = make_finding(
        tool="harness",
        rule_id="HARNESS-BLOCKER",
        category="Security & Privacy",
        severity="Critical",
        confidence="certain",
        message="Critical correctness issue",
        path="src/foo.py",
        start_line=1,
        end_line=1,
        source="agent",
    )
    conclusion = decide_approval([blocker], run_succeeded=True, tier="trusted")
    assert conclusion == "failure"
