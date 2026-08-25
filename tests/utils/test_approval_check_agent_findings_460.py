"""#460 — mergecraft-approval check-run reflects agent blockers (D7).

The gate today reads only ``analyzer_run.findings``. Agent Critical/Major
findings never reach ``mergecraft-approval``, so a review that requested
changes still posts ``neutral``. D7: consume the findings the review
produced; packet ``request_changes`` matches check ``failure``. Empty-list
and untrusted guards stay. CI SARIF is #464 / AG.

These assertions fail until the AF implementation wave. Do not xfail.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evidence.run_packet import build_run_packet, prepare_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, report_status_checks

PR_HEAD_SHA = "aaa1111111111111111111111111111111111111111"
_BLOCKING = ("Critical", "Major")


class _RecordingGitHub(GitHubClient):
    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.check_runs: list[dict[str, Any]] = []

    async def get_pull(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        return {"head": {"sha": PR_HEAD_SHA}}

    async def post(self, path: str, **kwargs: Any) -> Any:
        if path.endswith("/check-runs"):
            body = kwargs.get("json")
            if isinstance(body, dict):
                self.check_runs.append(body)
        return {}


def _finding(*, severity: str, source: str, rule_id: str, path: str) -> Finding:
    return make_finding(
        tool="agent" if source == "agent" else "ruff",
        rule_id=rule_id,
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message=f"{severity} {source} finding",
        path=path,
        start_line=1,
        end_line=1,
        source=source,  # type: ignore[arg-type]
        fingerprint=f"af460-check-{source}-{rule_id}",
    )


def _ctx(
    tmp_path: Path,
    *,
    github: _RecordingGitHub,
    agent_findings: list[Finding] | None = None,
    analyzer_findings: list[Finding] | None = None,
    analyzer_ran: bool = False,
    trust_tier: str = "trusted",
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.analyzer_run = AnalyzerRunState(
        ran=analyzer_ran,
        findings=[row.model_dump() for row in (analyzer_findings or [])],
    )
    tool_state.agent_findings = [row.model_dump() for row in (agent_findings or [])]
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=42, is_pr=True),
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
        trust_tier=trust_tier,  # type: ignore[arg-type]
        resolved_model="claude-sonnet-4-5",
    )


def _approval_run(github: _RecordingGitHub) -> dict[str, Any]:
    matches = [run for run in github.check_runs if run.get("name") == APPROVAL_CHECK]
    assert matches, f"expected a {APPROVAL_CHECK} check-run, got {github.check_runs!r}"
    return matches[0]


async def _report(ctx: ToolContext, *, run_succeeded: bool = True) -> None:
    await report_status_checks(
        ctx,
        run_succeeded=run_succeeded,
        packet=prepare_run_packet(ctx, run_succeeded=run_succeeded),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", _BLOCKING)
async def test_agent_blocker_makes_approval_check_failure(tmp_path: Path, severity: str) -> None:
    """D7: agent Critical/Major can make mergecraft-approval ``failure``."""
    github = _RecordingGitHub()
    agent = _finding(severity=severity, source="agent", rule_id="AGENT-GATE", path="src/auth.py")
    ctx = _ctx(tmp_path, github=github, agent_findings=[agent], analyzer_ran=False)

    await _report(ctx)

    approval = _approval_run(github)
    assert approval["conclusion"] == "failure", (
        "D7: agent blockers must reach the approval check; empty analyzer_run "
        f"must not freeze the gate at neutral (got {approval['conclusion']!r})"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("severity", _BLOCKING)
async def test_packet_request_changes_matches_approval_check(tmp_path: Path, severity: str) -> None:
    """D7: packet ``request_changes`` and check ``failure`` describe the same review."""
    github = _RecordingGitHub()
    agent = _finding(severity=severity, source="agent", rule_id="AGENT-MATCH", path="src/auth.py")
    ctx = _ctx(tmp_path, github=github, agent_findings=[agent], analyzer_ran=False)

    await _report(ctx)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    approval = _approval_run(github)
    assert packet.decision is not None
    assert packet.decision.action == "request_changes"
    assert packet.decision.verdict == "failure"
    assert approval["conclusion"] == "failure"
    assert approval["conclusion"] == packet.decision.verdict


@pytest.mark.asyncio
async def test_gate_reads_agent_findings_when_analyzer_list_is_empty(tmp_path: Path) -> None:
    """#460 log shape: analyzers findings=0, agent produced the review findings."""
    github = _RecordingGitHub()
    agent = _finding(severity="Major", source="agent", rule_id="AGENT-ONLY", path="src/leak.py")
    ctx = _ctx(
        tmp_path,
        github=github,
        agent_findings=[agent],
        analyzer_findings=[],
        analyzer_ran=False,
    )

    await _report(ctx)

    approval = _approval_run(github)
    summary = str((approval.get("output") or {}).get("summary") or "")
    assert approval["conclusion"] == "failure"
    assert "Findings: 0" not in summary
    assert "Has blocker: True" in summary


@pytest.mark.asyncio
async def test_analyzer_major_still_fails_the_gate(tmp_path: Path) -> None:
    """D7 consumes agent + analyzer; analyzer blockers must keep working."""
    github = _RecordingGitHub()
    analyzer = _finding(severity="Major", source="analyzer", rule_id="RUFF-M", path="src/x.py")
    ctx = _ctx(
        tmp_path,
        github=github,
        analyzer_findings=[analyzer],
        analyzer_ran=True,
        trust_tier="trusted",
    )

    await _report(ctx)

    assert _approval_run(github)["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_empty_findings_do_not_silently_succeed(tmp_path: Path) -> None:
    """D7: empty-list guard stays."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, agent_findings=[], analyzer_ran=True, trust_tier="trusted")

    await _report(ctx)

    assert _approval_run(github)["conclusion"] != "success"
    assert _approval_run(github)["conclusion"] == "neutral"


@pytest.mark.asyncio
async def test_untrusted_tier_does_not_silently_succeed(tmp_path: Path) -> None:
    """D7: untrusted guard stays — never success."""
    github = _RecordingGitHub()
    minor = _finding(severity="Minor", source="agent", rule_id="NIT", path="src/n.py")
    ctx = _ctx(
        tmp_path,
        github=github,
        agent_findings=[minor],
        trust_tier="untrusted",
    )

    await _report(ctx)

    assert _approval_run(github)["conclusion"] != "success"
