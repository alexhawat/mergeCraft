"""#464 — mergecraft-approval check-run reflects blocking CI SARIF (D8).

A ruff finding parsed from a CI SARIF artifact must make the approval
check ``failure``, matching packet ``request_changes``. Warning-level
SARIF and empty CI evidence must not silently succeed.

These assertions fail until the AG implementation wave. Do not xfail.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from mergecraft.ci.evidence import record_ci_findings, sarif_findings
from mergecraft.evidence.run_packet import build_run_packet
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from mergecraft.utils.status_checks import APPROVAL_CHECK, report_status_checks

PR_HEAD_SHA = "bbb2222222222222222222222222222222222222222"


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


def _sarif(*, level: str, rule_id: str = "F401") -> str:
    return json.dumps(
        {
            "version": "2.1.0",
            "runs": [
                {
                    "tool": {"driver": {"name": "ruff", "rules": [{"id": rule_id}]}},
                    "results": [
                        {
                            "ruleId": rule_id,
                            "level": level,
                            "message": {"text": f"ruff {rule_id}"},
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


def _ctx(tmp_path: Path, *, github: _RecordingGitHub, trust_tier: str = "trusted") -> ToolContext:
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
        ci_sarif_artifacts=["ruff-sarif"],
    )


def _approval_run(github: _RecordingGitHub) -> dict[str, Any]:
    matches = [run for run in github.check_runs if run.get("name") == APPROVAL_CHECK]
    assert matches, f"expected a {APPROVAL_CHECK} check-run, got {github.check_runs!r}"
    return matches[0]


@pytest.mark.asyncio
async def test_ruff_ci_sarif_makes_approval_check_failure(tmp_path: Path) -> None:
    """D8: a ruff finding from CI SARIF can reach the approval gate as failure."""
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    record_ci_findings(
        ctx.tool_state,
        sarif_findings(_sarif(level="error"), artifact="ruff-sarif", repo_root=tmp_path),
    )

    await report_status_checks(ctx, run_succeeded=True)

    assert _approval_run(github)["conclusion"] == "failure", (
        "D8: CI SARIF ruff error must fail mergecraft-approval; clamping to "
        f"non-blocking must not freeze the gate (got {_approval_run(github)!r})"
    )


@pytest.mark.asyncio
async def test_packet_request_changes_matches_ci_sarif_approval_check(tmp_path: Path) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    record_ci_findings(
        ctx.tool_state,
        sarif_findings(_sarif(level="error"), artifact="ruff-sarif", repo_root=tmp_path),
    )

    await report_status_checks(ctx, run_succeeded=True)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    assert packet.decision is not None
    assert packet.decision.action == "request_changes"
    assert packet.decision.verdict == "failure"
    assert _approval_run(github)["conclusion"] == packet.decision.verdict


@pytest.mark.asyncio
async def test_warning_ci_sarif_does_not_fail_the_gate(tmp_path: Path) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)
    record_ci_findings(
        ctx.tool_state,
        sarif_findings(
            _sarif(level="warning", rule_id="E501"), artifact="ruff-sarif", repo_root=tmp_path
        ),
    )

    await report_status_checks(ctx, run_succeeded=True)

    assert _approval_run(github)["conclusion"] != "failure"


@pytest.mark.asyncio
async def test_empty_ci_evidence_does_not_silently_succeed(tmp_path: Path) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github)

    await report_status_checks(ctx, run_succeeded=True)

    assert _approval_run(github)["conclusion"] != "success"
    assert _approval_run(github)["conclusion"] == "neutral"


@pytest.mark.asyncio
async def test_untrusted_tier_does_not_succeed_with_ci_sarif(tmp_path: Path) -> None:
    github = _RecordingGitHub()
    ctx = _ctx(tmp_path, github=github, trust_tier="untrusted")
    record_ci_findings(
        ctx.tool_state,
        sarif_findings(_sarif(level="error"), artifact="ruff-sarif", repo_root=tmp_path),
    )

    await report_status_checks(ctx, run_succeeded=True)

    assert _approval_run(github)["conclusion"] != "success"
