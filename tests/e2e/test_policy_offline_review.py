"""An offline review of a pull request that weakens its own policy fails closed.

End to end over the offline path: a real repository whose base commit carries
one ``blocking`` rule and one ``required`` rule, a pull request that touches the
guarded path while downgrading the blocking rule and adding a waiver for itself,
and a scripted agent that submits ``approve`` through the real terminal tool.

The run must record ``request_changes``, and the packet must carry the base
commit's two rule rows plus the advisory "this change takes effect after merge"
row — never the waiver the pull request wrote for itself.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from mergecraft.agents.shared import AgentResult
from mergecraft.config.settings import RepoSettings
from mergecraft.review import offline_agent
from mergecraft.utils.offline_diff import DiffMaterialization
from tests.support.policy_fixtures import (
    RULES_REL,
    commit_all,
    exception,
    init_git_repo,
    rule,
    write_policy,
)
from tests.support.tool_context import make_tool_context

if TYPE_CHECKING:
    from pathlib import Path

_BILLING_SCOPE = {"path": "src/billing/**"}
_BLOCKING_RULE = "billing.no-secret-in-source"
_REQUIRED_RULE = "billing.readiness-evidence"
_CHANGED_IN_PR = "policy.changed_in_pr"


def _build_pull_request(tmp_path: Path) -> tuple[Path, str, str, Path]:
    """Create the base/head repository pair and return the materialized diff."""
    repo = init_git_repo(tmp_path / "repo")
    (repo / "src" / "billing").mkdir(parents=True)
    (repo / "src" / "billing" / "x.py").write_text("VALUE = 1\n", encoding="utf-8")
    write_policy(
        repo,
        rules=[
            rule(_BLOCKING_RULE, severity="Major", enforcement="blocking", scope=_BILLING_SCOPE),
            rule(
                _REQUIRED_RULE,
                severity="Major",
                enforcement="required",
                scope=_BILLING_SCOPE,
                evidence_required=["health_check"],
            ),
        ],
    )
    base = commit_all(repo, "base: the policy that judges this review")

    # The pull request touches the guarded path, downgrades the blocking rule
    # and adds an exception that would waive it for this very change.
    (repo / "src" / "billing" / "x.py").write_text("VALUE = 2\n", encoding="utf-8")
    write_policy(
        repo,
        rules=[
            rule(_BLOCKING_RULE, severity="Minor", enforcement="advisory", scope=_BILLING_SCOPE),
            rule(
                _REQUIRED_RULE,
                severity="Major",
                enforcement="required",
                scope=_BILLING_SCOPE,
                evidence_required=["health_check"],
            ),
        ],
        exceptions=[exception(exception_id="self-waiver", rule_id=_BLOCKING_RULE)],
    )
    head = commit_all(repo, "pr: touch billing, weaken the rule, waive itself")

    diff_path = tmp_path / "pull-request.diff"
    diff_path.write_text(
        offline_agent_diff(repo, base=base, head=head),
        encoding="utf-8",
    )
    return repo, base, head, diff_path


def offline_agent_diff(repo: Path, *, base: str, head: str) -> str:
    """The unified diff the offline review is handed."""
    from tests.support.policy_fixtures import git

    return git(repo, "diff", f"{base}..{head}")


@pytest.fixture
def offline_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """Point the offline path at a scripted agent and a keyless settings object."""
    from mergecraft.utils.agent_resolve import CredentialStatus

    repo, base, head, diff_path = _build_pull_request(tmp_path)
    monkeypatch.delenv("GITHUB_BASE_REF", raising=False)
    monkeypatch.setattr(
        offline_agent,
        "load_repo_settings",
        lambda **_: RepoSettings(models=["anthropic/claude-sonnet"]),
    )
    monkeypatch.setattr(
        offline_agent,
        "start_mcp_http_server",
        lambda *args, **kwargs: ("http://localhost:1/mcp", lambda: None),
    )
    monkeypatch.setattr(offline_agent, "install_bundled_skills", lambda **_: None)
    monkeypatch.setattr(
        offline_agent,
        "credential_status_for_slug",
        lambda *args, **kwargs: CredentialStatus(available=True, source=None, looked_for=()),
    )
    return {
        "repo": repo,
        "base": base,
        "head": head,
        "diff_path": diff_path,
        "submitted": {},
        "tool_state": {},
    }


def _install_scripted_agent(
    monkeypatch: pytest.MonkeyPatch,
    dispatch: dict[str, Any],
) -> None:
    """An agent that reads the diff and submits ``approve`` through the real tool."""
    from mergecraft.mcp.tool_state import primary_repo_state
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    tmp_root = dispatch["diff_path"].parent

    class _ScriptedAgent:
        name = "claude"

        async def install(self) -> None:
            return None

        async def run(self, ctx: Any) -> AgentResult:
            dispatch["tool_state"]["state"] = ctx.tool_state
            # The Action path's checkout records the PR base before review; the
            # offline fixture states the same provenance for its materialized diff.
            primary = primary_repo_state(ctx.tool_state)
            primary.before_sha = dispatch["base"]
            primary.checkout_sha = dispatch["head"]
            # This agent read the diff it was handed, so the one-time coverage
            # nudge has already been served.
            ctx.tool_state.diff_coverage_nudge_sent = True
            tool_ctx = make_tool_context(
                tmp_root,
                trust_tier="trusted",
                tool_state=ctx.tool_state,
            )
            submitted = await submit_review_verdict_tool(tool_ctx).execute(
                {"verdict": "approve", "summary": "LGTM", "findings": []}
            )
            dispatch["submitted"]["result"] = submitted
            return AgentResult(success=True, terminal_submission_received=True)

    monkeypatch.setattr(offline_agent, "resolve_runtime_agent", lambda **_: _ScriptedAgent())


@pytest.mark.asyncio
async def test_offline_review_of_a_self_weakening_pr_still_requests_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offline_dispatch: dict[str, Any],
) -> None:
    """The recorded verdict, the submitted summary and the packet all agree."""
    dispatch = offline_dispatch
    _install_scripted_agent(monkeypatch, dispatch)
    packet_path = tmp_path / "policy-packet.json"
    tmpdir = tmp_path / "tmp"
    tmpdir.mkdir()

    result = await offline_agent.run_offline_agent_review(
        cwd=dispatch["repo"],
        materialization=DiffMaterialization(
            path=dispatch["diff_path"],
            base_ref=dispatch["base"],
            line_count=40,
            empty=False,
        ),
        prompt="review",
        model=None,
        tmpdir=tmpdir,
        evidence_packet_path=packet_path,
    )

    assert dispatch["submitted"].get("result") is not None
    assert dispatch["submitted"]["result"].is_error is False
    tool_state = dispatch["tool_state"]["state"]
    submission = tool_state.terminal_submission
    assert submission is not None
    assert submission.verdict == "request_changes"
    assert "Policy rules" in submission.summary
    assert _BLOCKING_RULE in submission.summary

    assert result.success, result.error
    assert result.evidence_packet_path is not None
    packet = json.loads(packet_path.read_text(encoding="utf-8"))
    policy_rows = [row for row in packet["findings"] if row.get("tool") == "policy"]
    by_rule = {row["rule_id"]: row for row in policy_rows}

    assert _BLOCKING_RULE in by_rule, policy_rows
    assert _REQUIRED_RULE in by_rule, policy_rows
    assert _CHANGED_IN_PR in by_rule, policy_rows

    blocking_row = by_rule[_BLOCKING_RULE]
    assert blocking_row["severity"] == "Major", "the base rule judges the PR, not the head copy"
    assert "health_check" in " ".join(by_rule[_REQUIRED_RULE]["evidence"])
    assert any(f"base:{dispatch['base']}" in item for item in blocking_row["evidence"])
    assert any("sha256:" in item for item in blocking_row["evidence"])
    assert RULES_REL in " ".join(blocking_row["evidence"])

    assert "self-waiver" not in json.dumps(policy_rows), "a PR-owned waiver must not apply"
    assert "merge" in json.dumps(by_rule[_CHANGED_IN_PR]).casefold()

    assert packet["decision"]["verdict"] == "failure"
