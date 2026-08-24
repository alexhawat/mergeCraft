"""#464 — evidence packet sees blocking CI SARIF (D8).

A ruff SARIF error ingested as CI evidence must reach ``decide_approval``
on the packet path as ``failure`` / ``request_changes``. Empty-list and
untrusted guards stay.

These assertions fail until the AG implementation wave. Do not xfail.
"""

from __future__ import annotations

import json
from pathlib import Path

from mergecraft.agents.gates import decide_approval
from mergecraft.ci.evidence import record_ci_findings, sarif_findings
from mergecraft.evidence.run_packet import build_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

_BLOCKING = frozenset({"Critical", "Major"})


def _ruff_error_sarif() -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "ruff", "rules": [{"id": "F401"}]}},
                    "results": [
                        {
                            "ruleId": "F401",
                            "level": "error",
                            "message": {"text": "unused import `os`"},
                            "locations": [
                                {
                                    "physicalLocation": {
                                        "artifactLocation": {"uri": "src/app.py"},
                                        "region": {"startLine": 3, "endLine": 3},
                                    }
                                }
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _ctx(tmp_path: Path, *, trust_tier: str = "trusted") -> ToolContext:
    tool_state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    tool_state.analyzer_run = AnalyzerRunState(ran=False, findings=[])
    tool_state.agent_findings = []
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
        ci_sarif_artifacts=["ruff-sarif"],
    )


def test_packet_from_ci_ruff_sarif_fails_decide_approval(tmp_path: Path) -> None:
    """D8: ingested ruff SARIF error is in the packet and yields verdict failure."""
    ctx = _ctx(tmp_path)
    parsed = sarif_findings(_ruff_error_sarif(), artifact="ruff-sarif", repo_root=tmp_path)
    record_ci_findings(ctx.tool_state, parsed)

    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    sources = {finding.source for finding in packet.findings}
    assert "ci" in sources, (
        "D8: the packet must include CI SARIF findings, not only agent/analyzer "
        f"(got sources={sources!r} count={len(packet.findings)})"
    )
    assert any(item.severity in _BLOCKING for item in packet.findings), (
        "D8: ruff CI SARIF error must keep a blocking severity on the packet"
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure", (
        f"D8: ruff CI SARIF must reach the gate as failure, not {decision.verdict!r}"
    )


def test_packet_request_changes_for_ci_ruff_sarif(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    record_ci_findings(
        ctx.tool_state,
        sarif_findings(_ruff_error_sarif(), artifact="ruff-sarif", repo_root=tmp_path),
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    assert packet.decision is not None
    assert packet.decision.verdict == "failure"
    assert packet.decision.action == "request_changes", (
        "D8: packet action must be request_changes so it matches a failure check "
        f"(got action={packet.decision.action!r} verdict={packet.decision.verdict!r})"
    )


def test_empty_ci_evidence_stays_neutral(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"


def test_untrusted_never_succeeds_with_ci_ruff_sarif(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, trust_tier="untrusted")
    record_ci_findings(
        ctx.tool_state,
        sarif_findings(_ruff_error_sarif(), artifact="ruff-sarif", repo_root=tmp_path),
    )
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)
    decision = decide_approval(packet, run_succeeded=True, tier="untrusted")
    assert decision.verdict != "success"
