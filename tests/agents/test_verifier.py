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


def test_verifier_deny_list_is_independent_and_non_empty(tmp_path: Path) -> None:
    """H4 — verifier complement is independent of the reviewer/subagent complement."""
    verifier = import_module("mergecraft.agents.verifier")
    ctx = _ctx(tmp_path)
    denied = verifier.verifier_denied_tool_names(ctx)
    subagent_denied = subagent_denied_tool_names(ctx)
    assert denied
    assert denied != subagent_denied
    assert "push_branch" in denied
    assert "push_branch" in subagent_denied
    # Verifier deny list includes scope tools the reviewer allow-list keeps.
    assert "checkout_pr" in denied
    assert "checkout_pr" not in subagent_denied
    # Subagent deny list includes verification tools the verifier allow-list keeps.
    assert "verify_agent_findings" in subagent_denied
    assert "verify_agent_findings" not in denied


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


def test_verifier_prompt_covers_agent_authored_findings() -> None:
    """The subagent used to be told it only ever judged analyzer output (C6)."""
    verifier = import_module("mergecraft.agents.verifier")
    prompt = verifier.VERIFIER_SYSTEM_PROMPT
    assert "written by the reviewing agent" in prompt
    assert "SECONDARY signal" in prompt


def test_rubric_is_outcome_based_and_versioned() -> None:
    """W13.2 — binary observable outcomes, never a 'quality' or verbosity score."""
    verifier = import_module("mergecraft.agents.verifier")
    keys = [key for key, _ in verifier.VERIFIER_RUBRIC]
    assert keys == [
        "cited-code-exists",
        "mechanism-holds",
        "reachable",
        "introduced-here",
        "not-already-refuted",
    ]
    text = " ".join(f"{key} {body}" for key, body in verifier.VERIFIER_RUBRIC).casefold()
    for banned in ("quality", "verbose", "verbosity", "style", "readable"):
        assert banned not in text
    assert verifier.VERIFIER_RUBRIC_VERSION
    for _key, body in verifier.VERIFIER_RUBRIC:
        assert body.endswith(".")


def test_judge_pin_is_recorded_even_when_the_provider_is_unpinned() -> None:
    """An unpinned judge is a fact to log, not a reason to log nothing (#45)."""
    verifier = import_module("mergecraft.agents.verifier")
    pinned = verifier.judge_pin(provider="claude", resolved_model="claude-opus-5")
    assert pinned.model == "claude-sonnet-5"
    assert pinned.model_pinned is True
    assert pinned.rubric_version == verifier.VERIFIER_RUBRIC_VERSION
    assert pinned.judge_version == verifier.VERIFIER_JUDGE_VERSION

    loose = verifier.judge_pin(provider="opencode", resolved_model="openai/gpt-5")
    assert loose.model == "openai/gpt-5"
    assert loose.model_pinned is False


def test_dispatched_claude_judge_model_matches_the_recorded_pin() -> None:
    """The pin is worthless if the agent definition dispatches a different model."""
    import json

    verifier = import_module("mergecraft.agents.verifier")
    claude = import_module("mergecraft.agents.claude")
    agents = json.loads(claude.build_agents_json())
    dispatched = agents[verifier.VERIFIER_AGENT_NAME]["model"]
    assert dispatched == verifier.judge_pin(provider="claude").model


def test_verdict_is_refused_when_no_deterministic_check_ran(tmp_path: Path) -> None:
    """W13.3 — tools settle checkable facts before any judge evaluation counts."""
    verifier = import_module("mergecraft.agents.verifier")
    verdict = verifier.JudgeVerdict(
        fingerprint="a" * 24,
        verdict="drop",
        reason="looks fine to me",
        pin=verifier.judge_pin(provider="claude"),
        deterministic_checks=[],
    )
    with pytest.raises(ValueError, match="secondary evaluators"):
        verifier.record_verifier_verdict(verdict, learnings_path=tmp_path / "learnings.md")
    assert not (tmp_path / "learnings.md").exists()


def test_high_stakes_lane_needs_more_than_one_judge(tmp_path: Path) -> None:
    """W13.4 — a single judge cannot retire a finding on the `high` lane."""
    verifier = import_module("mergecraft.agents.verifier")
    learnings = tmp_path / "learnings.md"
    outcome = verifier.record_verifier_verdict(
        verifier.JudgeVerdict(
            fingerprint="b" * 24,
            verdict="drop",
            reason="could not reproduce",
            pin=verifier.judge_pin(provider="claude"),
            deterministic_checks=["run_analyzers"],
            lane="high",
        ),
        learnings_path=learnings,
    )
    assert outcome.escalated_to_human is True
    assert outcome.recorded_withdrawn is False
    assert outcome.publishable is True
    assert not learnings.exists()


def test_agent_finding_identity_matches_the_published_fingerprint() -> None:
    """The withdrawn-skip only works if both ends derive the same identity."""
    verifier = import_module("mergecraft.agents.verifier")
    taxonomy = import_module("mergecraft.review_taxonomy")
    finding = verifier.AgentFinding(
        path="src/app.py", body="the retry double-charges", severity="Major"
    )
    assert finding.identity() == taxonomy.finding_fingerprint(
        path="src/app.py", body="the retry double-charges"
    )


def test_two_agent_findings_on_one_path_get_distinct_identities() -> None:
    """PR #93 replaced a shared literal with per-item fingerprints; hold that."""
    verifier = import_module("mergecraft.agents.verifier")
    first = verifier.AgentFinding(path="src/app.py", body="first problem", severity="Critical")
    second = verifier.AgentFinding(path="src/app.py", body="second problem", severity="Critical")
    assert first.identity() != second.identity()


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
