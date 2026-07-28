"""Verification agent — read-only gate and withdrawn findings (D11)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.analyzers.support import import_module

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import WITHDRAWN_FINDINGS_HEADING
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.xfail(reason="green after W7: verification agent", strict=False)


def _ctx(tmp_path: Path) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"),
            shell="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


def test_verifier_deny_list_derived_from_mutates_non_empty(tmp_path: Path) -> None:
    verifier = import_module("mergecraft.agents.verifier")
    ctx = _ctx(tmp_path)
    denied = verifier.verifier_denied_tool_names(ctx)
    assert denied
    assert denied == subagent_denied_tool_names(ctx)
    assert "push_branch" in denied


@pytest.mark.parametrize("severity", ["Critical", "Major"])
def test_only_critical_and_major_reach_verifier(severity: str) -> None:
    verifier = import_module("mergecraft.agents.verifier")
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="zizmor",
        rule_id="unpinned-uses-ref",
        category="Security & Privacy",
        severity=severity,
        confidence="likely",
        message="unpinned action",
        path=".github/workflows/unpinned-action.yml",
        start_line=11,
        end_line=11,
        source="analyzer",
    )
    assert verifier.should_verify(finding) is True


@pytest.mark.parametrize("severity", ["Minor", "Trivial"])
def test_minor_and_below_skip_verifier(severity: str) -> None:
    verifier = import_module("mergecraft.agents.verifier")
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="shellcheck",
        rule_id="SC2086",
        category="Maintainability & Code Quality",
        severity=severity,
        confidence="likely",
        message="quote variable",
        path="scripts/deploy.sh",
        start_line=5,
        end_line=5,
        source="analyzer",
    )
    assert verifier.should_verify(finding) is False


def test_dropped_finding_writes_withdrawn_reason(tmp_path: Path) -> None:
    verifier = import_module("mergecraft.agents.verifier")
    learnings = tmp_path / "learnings.md"
    learnings.write_text("# Learnings\n", encoding="utf-8")
    verifier.record_withdrawn_finding(
        learnings_path=learnings,
        reason="False positive — context only available on pull_request.",
        fingerprint="abc123",
    )
    body = learnings.read_text(encoding="utf-8")
    assert WITHDRAWN_FINDINGS_HEADING in body
    assert "False positive" in body
