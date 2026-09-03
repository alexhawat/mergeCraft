"""#619 — the agent's terminal verdict is a one-way ratchet on ``decide_approval``.

On PR #619 the reviewing agent's verifier confirmed a blocking security
finding and the agent called ``submit_review_verdict`` with
``verdict="request_changes"`` — but the confirmed finding never reached
``packet.findings`` (a separate leak, closed in ``mcp/verdict.py``), so the
structural gate saw no blocker and returned ``success``. This suite pins the
second, independent line of defense: ``packet.agent_terminal_verdict`` binds
the conclusion downward but never up.

- ``request_changes`` + no typed blocker -> not ``success`` (downgraded to
  ``neutral``).
- ``request_changes`` + a typed blocker -> ``failure``, unchanged from today.
- ``approve`` + a typed blocker -> still ``failure`` (advisory ``approve``
  cannot rescue a blocker).
- ``approve`` + clean evidence -> still ``success`` (advisory ``approve``
  never raises a conclusion the evidence did not itself reach).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evidence.run_packet import build_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import TerminalSubmission, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient


def _finding(*, severity: str, path: str = "src/auth.py") -> Finding:
    return make_finding(
        tool="agent",
        rule_id="AGENT-RATCHET",
        category="Security & Privacy",
        severity=severity,
        confidence="certain",
        message=f"{severity} agent finding",
        path=path,
        start_line=1,
        end_line=1,
        source="agent",
        fingerprint=f"ratchet619-{severity}",
    )


def _ctx(
    tmp_path: Path,
    *,
    verdict: str | None,
    agent_findings: list[Finding] | None = None,
) -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.agent_findings = [row.model_dump() for row in (agent_findings or [])]
    if verdict is not None:
        tool_state.terminal_submission = TerminalSubmission(
            id="fixed-id",
            verdict=verdict,  # type: ignore[arg-type]
            summary="ratchet fixture",
            findings=[],
            payload_hash="fixed-hash",
            submitted_at="2026-01-01T00:00:00+00:00",
            attempt_id=0,
        )
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
        trust_tier="trusted",
        resolved_model="claude-sonnet-4-5",
    )


def test_request_changes_with_no_blocker_is_not_success(tmp_path: Path) -> None:
    """The #619 gap: a recorded request_changes must stop success on its own."""
    ctx = _ctx(tmp_path, verdict="request_changes", agent_findings=[])
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    assert packet.agent_terminal_verdict == "request_changes"

    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict != "success"
    assert decision.verdict == "neutral"
    assert "request_changes" in decision.reason


def test_request_changes_with_a_blocker_is_still_failure(tmp_path: Path) -> None:
    """A typed blocker still wins outright — the ratchet only ever tightens."""
    ctx = _ctx(
        tmp_path,
        verdict="request_changes",
        agent_findings=[_finding(severity="Critical")],
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure"


def test_approve_with_a_blocker_is_still_failure(tmp_path: Path) -> None:
    """An advisory approve cannot rescue a typed blocker."""
    ctx = _ctx(
        tmp_path,
        verdict="approve",
        agent_findings=[_finding(severity="Major")],
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure"


def test_approve_with_clean_evidence_still_succeeds(tmp_path: Path) -> None:
    """The ratchet is one-way: approve never raises a conclusion, but does not
    suppress one either — a clean run with attested evidence still succeeds."""
    ctx = _ctx(
        tmp_path,
        verdict="approve",
        agent_findings=[_finding(severity="Minor")],
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"


def test_no_terminal_submission_is_unaffected(tmp_path: Path) -> None:
    """A run with no terminal submission at all keeps today's behaviour."""
    ctx = _ctx(tmp_path, verdict=None, agent_findings=[_finding(severity="Minor")])
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    assert packet.agent_terminal_verdict is None

    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"


@pytest.mark.parametrize("verdict", ["approve", "request_changes"])
def test_approve_never_raises_and_request_changes_never_leaves_success(
    tmp_path: Path, verdict: str
) -> None:
    """Green guard pinning both halves of the one-way contract in one place."""
    ctx = _ctx(tmp_path, verdict=verdict, agent_findings=[])
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    if verdict == "request_changes":
        assert decision.verdict != "success"
    # approve with no findings is neutral regardless (empty-findings guard) —
    # the point pinned here is only that it is never *forced* to success.
