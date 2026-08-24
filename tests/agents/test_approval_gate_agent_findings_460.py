"""#460 — approval gate consumes agent findings via the evidence packet (D7).

Locked D7 (open-issues-sweep-2026-08-24-a):

- The gate decides from the findings the review produced (agent + analyzer).
- Prefer ``decide_approval`` on the ``MergeEvidencePacket`` path in
  ``agents/gates.py``.
- Empty-list and untrusted guards stay — do not start silently approving.
- Packet ``request_changes`` matches a ``failure`` approval check.
- CI evidence is #464 / AG — out of this file.

These assertions fail until the AF implementation wave. Do not xfail.
Do not edit ``src/mergecraft/``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evidence.run_packet import build_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_BLOCKING = ("Critical", "Major")


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
        fingerprint=f"af460-{source}-{rule_id}",
    )


def _ctx(
    tmp_path: Path,
    *,
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
        github=GitHubClient(token="test-token"),
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


@pytest.mark.parametrize("severity", _BLOCKING)
def test_packet_from_run_carries_agent_blocker_into_decide_approval(
    tmp_path: Path, severity: str
) -> None:
    """D7: ``build_run_packet`` + ``decide_approval(packet)`` see agent blockers."""
    agent = _finding(severity=severity, source="agent", rule_id="AGENT-BLOCK", path="src/auth.py")
    ctx = _ctx(tmp_path, agent_findings=[agent], analyzer_ran=False)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    sources = {finding.source for finding in packet.findings}
    assert "agent" in sources, (
        "D7: the packet must include agent findings, not only analyzer_run.findings "
        f"(got sources={sources!r} count={len(packet.findings)})"
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure", (
        f"D7: agent {severity} on the packet path must yield verdict failure, "
        f"not {decision.verdict!r}"
    )


@pytest.mark.parametrize("severity", _BLOCKING)
def test_packet_request_changes_for_agent_blocker(tmp_path: Path, severity: str) -> None:
    """D7: packet ``action=request_changes`` when the agent raised a blocker."""
    agent = _finding(severity=severity, source="agent", rule_id="AGENT-RC", path="src/auth.py")
    ctx = _ctx(tmp_path, agent_findings=[agent], analyzer_ran=False)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    assert packet.decision is not None
    assert packet.decision.verdict == "failure"
    assert packet.decision.action == "request_changes", (
        "D7: packet action must be request_changes so it matches a failure check "
        f"(got action={packet.decision.action!r} verdict={packet.decision.verdict!r})"
    )


def test_packet_unions_agent_and_analyzer_findings(tmp_path: Path) -> None:
    """D7: gate input is agent + analyzer; CI is AG #464 and is not required here."""
    agent = _finding(severity="Critical", source="agent", rule_id="AGENT-U", path="src/a.py")
    analyzer = _finding(severity="Minor", source="analyzer", rule_id="RUFF-U", path="src/b.py")
    ctx = _ctx(
        tmp_path,
        agent_findings=[agent],
        analyzer_findings=[analyzer],
        analyzer_ran=True,
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    sources = {finding.source for finding in packet.findings}
    assert "agent" in sources, f"D7: packet missing agent findings (got {sources!r})"
    assert "analyzer" in sources, f"D7: packet missing analyzer findings (got {sources!r})"
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure"


def test_empty_findings_stay_neutral_not_success(tmp_path: Path) -> None:
    """D7: empty-list guard stays — trusted + succeeded + no findings is not success."""
    ctx = _ctx(tmp_path, agent_findings=[], analyzer_findings=[], analyzer_ran=True)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict != "success"
    assert decision.verdict == "neutral"


def test_untrusted_tier_never_succeeds_even_with_agent_minor(tmp_path: Path) -> None:
    """D7: untrusted guard stays — do not start silently approving."""
    minor = _finding(severity="Minor", source="agent", rule_id="AGENT-NIT", path="src/n.py")
    ctx = _ctx(tmp_path, agent_findings=[minor], trust_tier="untrusted")
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    decision = decide_approval(packet, run_succeeded=True, tier="untrusted")
    assert decision.verdict != "success"
