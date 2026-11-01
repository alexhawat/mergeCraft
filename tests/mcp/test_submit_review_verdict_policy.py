"""Policy rows reach every seam that decides an approval verdict.

One gate, not two: a blocking policy rule contributes blocking findings and the
verdict authority stays in ``decide_approval``. The three seams a review uses —
the terminal submission, ``validate_submission`` and the evidence packet — must
agree, the agent must not be able to withdraw a policy row, and a repository
with no ``rules.yaml`` must record exactly what it recorded before.

The tests are written before the wiring exists, so the first run is red.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest
from tests.support.policy_fixtures import RULES_REL, row_text, rule, write_diff, write_policy
from tests.support.tool_context import bind_github_client, bind_review_publication_scope

from mergecraft.agents.post_run import finalize_agent_result
from mergecraft.agents.shared import AgentResult, AgentRunContext, ResolvedInstructions
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import TerminalSubmission, init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_BILLING_SCOPE = {"path": "src/billing/**"}
_REJECTION_APPROVE_BLOCKER = "approve_with_confirmed_blocker"


class _RecordingGitHub(GitHubClient):
    """Captures the review payloads a publication seam would have sent."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.review_payloads: list[dict[str, Any]] = []

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payloads.append(payload)
        return {
            "id": 1,
            "node_id": "n1",
            "html_url": "https://example.test/1",
            "state": payload.get("event") or "COMMENTED",
        }


def _ctx(tmp_path: Path) -> ToolContext:
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
        trust_tier="trusted",
    )


def _run_ctx(ctx: ToolContext) -> AgentRunContext:
    return AgentRunContext(
        payload=ctx.payload,
        mcp_server_url=ctx.mcp_server_url,
        tmpdir=ctx.tmpdir,
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(),
        tool_state=ctx.tool_state,
    )


def _bind_diff(ctx: ToolContext, tmp_path: Path, *paths: str) -> str:
    diff_path = str(write_diff(tmp_path, *paths, name=f"pr-{len(paths)}.diff"))
    primary_repo_state(ctx.tool_state).diff_path = diff_path
    return diff_path


def _approve() -> dict[str, Any]:
    return {"verdict": "approve", "summary": "No blocking issues in the diff.", "findings": []}


async def _submit(ctx: ToolContext, payload: dict[str, Any]) -> Any:
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    return await submit_review_verdict_tool(ctx).execute(payload)


async def _submit_approve_over_policy(
    tmp_path: Path,
    *,
    enforcement: str = "blocking",
    severity: str = "Major",
) -> ToolContext:
    ctx = _ctx(tmp_path)
    write_policy(
        tmp_path,
        rules=[
            rule(
                "billing.no-secret",
                severity=severity,
                enforcement=enforcement,
                scope=_BILLING_SCOPE,
            )
        ],
    )
    _bind_diff(ctx, tmp_path, "src/billing/x.py")
    return ctx


# ---------------------------------------------------------------------------
# terminal submission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_blocking_rule_turns_an_approve_into_request_changes(tmp_path: Path) -> None:
    """The recorded verdict, the recorded row and the summary all agree."""
    ctx = await _submit_approve_over_policy(tmp_path)

    result = await _submit(ctx, _approve())

    assert result.is_error is False, result.content[0]["text"]
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    assert submission.verdict == "request_changes"
    matching = [item for item in submission.findings if "billing.no-secret" in row_text(item)]
    assert len(matching) == 1, "the policy row is recorded once, not once per seam"
    assert "Policy rules" in submission.summary
    assert "billing.no-secret" in submission.summary
    assert "blocking" in submission.summary
    assert "Major" in submission.summary


@pytest.mark.asyncio
async def test_an_advisory_row_is_recorded_and_the_approve_stands(tmp_path: Path) -> None:
    """Advisory rules stay visible without closing the gate."""
    ctx = await _submit_approve_over_policy(tmp_path, enforcement="advisory", severity="Major")

    result = await _submit(ctx, _approve())

    assert result.is_error is False, result.content[0]["text"]
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    assert submission.verdict == "approve"
    matching = [item for item in submission.findings if "billing.no-secret" in row_text(item)]
    assert len(matching) == 1
    assert matching[0].severity == "Trivial"


@pytest.mark.asyncio
async def test_the_agent_cannot_withdraw_a_policy_fingerprint(tmp_path: Path) -> None:
    """``drop`` retires agent claims, not a server-computed policy row."""
    from mergecraft.policy.review import ensure_policy_evaluated

    ctx = await _submit_approve_over_policy(tmp_path)
    rows = ensure_policy_evaluated(ctx)
    assert len(rows) == 1

    ctx.tool_state.withdrawn_fingerprints.add(rows[0].fingerprint)

    result = await _submit(ctx, _approve())

    assert result.is_error is True
    assert _REJECTION_APPROVE_BLOCKER in result.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None


@pytest.mark.asyncio
async def test_approve_through_create_pull_request_review_is_rejected(tmp_path: Path) -> None:
    """The second publication entrypoint reads the same validation state."""
    from mergecraft.mcp.review import create_pull_request_review_tool

    github = _RecordingGitHub()
    ctx = _ctx(tmp_path)
    bind_github_client(ctx, github)
    bind_review_publication_scope(ctx, pr_number=7, checkout_sha="deadbeef")
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope=_BILLING_SCOPE)])
    # The publication scope helper writes a placeholder diff; the review scope
    # this test needs is the one that touches the rule's scope.
    write_diff(tmp_path, "src/billing/x.py", name="diff.patch")
    ctx.tool_state.pr_number = 7

    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Looks good to me.", "approved": True},
    )

    assert result.is_error is True
    assert _REJECTION_APPROVE_BLOCKER in result.content[0]["text"]
    assert ctx.tool_state.terminal_submission is None
    assert github.review_payloads == []


@pytest.mark.asyncio
async def test_post_run_revalidation_sees_the_policy_population(tmp_path: Path) -> None:
    """A stored ``approve`` is re-graded against policy at finalize time."""
    from mergecraft.policy.review import ensure_policy_evaluated

    ctx = await _submit_approve_over_policy(tmp_path)
    assert ensure_policy_evaluated(ctx)
    ctx.tool_state.terminal_submission = TerminalSubmission(
        id="sub-1",
        verdict="approve",
        summary="LGTM",
        findings=[],
        payload_hash="payload-hash",
        submitted_at="2026-01-01T00:00:00+00:00",
        attempt_id=ctx.tool_state.attempt_id,
    )

    finalized = await finalize_agent_result(_run_ctx(ctx), AgentResult(success=True))

    assert finalized.terminal_submission_received is False
    assert finalized.diagnostics.get("rejection_reason") == _REJECTION_APPROVE_BLOCKER


@pytest.mark.asyncio
async def test_resubmitting_an_identical_payload_stays_idempotent(tmp_path: Path) -> None:
    """A replay must not duplicate the row or change the recorded verdict."""
    ctx = await _submit_approve_over_policy(tmp_path, enforcement="advisory", severity="Minor")

    first = await _submit(ctx, _approve())
    second = await _submit(ctx, _approve())

    assert first.is_error is False, first.content[0]["text"]
    assert second.is_error is False, second.content[0]["text"]
    assert json.loads(second.content[0]["text"])["replayed"] is True
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    matching = [item for item in submission.findings if "billing.no-secret" in row_text(item)]
    assert len(matching) == 1


# ---------------------------------------------------------------------------
# validation state and the population withdrawal cannot touch
# ---------------------------------------------------------------------------


def test_validation_state_carries_policy_rows_outside_withdrawal(tmp_path: Path) -> None:
    """``ValidationState.policy_findings`` is a population of its own."""
    from mergecraft.policy.review import ensure_policy_evaluated

    from mergecraft.mcp.verdict import (
        validation_state_from_tool_context,
        validation_state_from_tool_state,
    )

    ctx = _ctx(tmp_path)
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope=_BILLING_SCOPE)])
    _bind_diff(ctx, tmp_path, "src/billing/x.py")
    rows = ensure_policy_evaluated(ctx)
    assert rows

    fingerprints = {row.fingerprint for row in rows}
    from_context = validation_state_from_tool_context(ctx)
    assert fingerprints <= {row.fingerprint for row in from_context.policy_findings}

    from_state = validation_state_from_tool_state(ctx.tool_state, tmpdir=ctx.tmpdir)
    assert fingerprints <= {row.fingerprint for row in from_state.policy_findings}

    ctx.tool_state.withdrawn_fingerprints |= fingerprints
    after_withdrawal = validation_state_from_tool_state(ctx.tool_state, tmpdir=ctx.tmpdir)
    assert fingerprints <= {row.fingerprint for row in after_withdrawal.policy_findings}


def test_policy_evaluation_is_computed_once_per_diff_path(tmp_path: Path) -> None:
    """One population per run: ``ensure_policy_evaluated`` caches on the diff."""
    from mergecraft.policy.review import ensure_policy_evaluated

    ctx = _ctx(tmp_path)
    write_policy(tmp_path, rules=[rule("rule-first", scope=_BILLING_SCOPE)])
    diff_path = _bind_diff(ctx, tmp_path, "src/billing/x.py")

    first = ensure_policy_evaluated(ctx)
    evaluation = ctx.tool_state.policy_evaluation
    assert evaluation is not None
    assert evaluation.diff_path == diff_path
    assert [row.fingerprint for row in evaluation.rows] == [row.fingerprint for row in first]

    # A rule added to disk after the run evaluated must not change this run.
    write_policy(
        tmp_path,
        rules=[
            rule("rule-first", scope=_BILLING_SCOPE),
            rule("rule-second", scope=_BILLING_SCOPE),
        ],
    )
    second = ensure_policy_evaluated(ctx)
    assert [row.fingerprint for row in second] == [row.fingerprint for row in first]


def test_a_new_diff_path_is_evaluated_again(tmp_path: Path) -> None:
    """The cache key is the diff, so a re-scoped run does not inherit stale rows."""
    from mergecraft.policy.review import ensure_policy_evaluated

    ctx = _ctx(tmp_path)
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope=_BILLING_SCOPE)])
    _bind_diff(ctx, tmp_path, "src/billing/x.py")
    assert len(ensure_policy_evaluated(ctx)) == 1

    new_diff = str(write_diff(tmp_path, "docs/readme.md", name="rescoped.diff"))
    primary_repo_state(ctx.tool_state).diff_path = new_diff

    assert ensure_policy_evaluated(ctx) == []
    evaluation = ctx.tool_state.policy_evaluation
    assert evaluation is not None
    assert evaluation.diff_path == new_diff


def test_an_unreadable_diff_is_one_blocking_major_unevaluated_row(tmp_path: Path) -> None:
    """A diff that cannot be read once scope exists blocks and names the path."""
    from mergecraft.policy.review import ensure_policy_evaluated

    ctx = _ctx(tmp_path)
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope=_BILLING_SCOPE)])
    missing = str(tmp_path / "missing.diff")
    primary_repo_state(ctx.tool_state).diff_path = missing

    rows = ensure_policy_evaluated(ctx)

    assert [row.rule_id for row in rows] == ["policy.unevaluated"]
    assert rows[0].severity == "Major"
    assert "missing.diff" in row_text(rows[0])


# ---------------------------------------------------------------------------
# no rules file, no change
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_rules_file_records_the_same_submission_as_before(tmp_path: Path) -> None:
    """A repository without a policy tree is byte-identical to today's review."""
    from mergecraft.policy.review import ensure_policy_evaluated

    from mergecraft.mcp.verdict import recorded_submission_payload

    recorded: list[dict[str, Any]] = []
    for name, make_policy_dir in (("absent", False), ("empty", True)):
        root = tmp_path / name
        root.mkdir()
        ctx = _ctx(root)
        _bind_diff(ctx, root, "src/billing/x.py")
        if make_policy_dir:
            (root / RULES_REL).parent.mkdir(parents=True, exist_ok=True)
        assert ensure_policy_evaluated(ctx) == []
        result = await _submit(ctx, _approve())
        assert result.is_error is False, result.content[0]["text"]
        submission = ctx.tool_state.terminal_submission
        assert submission is not None
        recorded.append(recorded_submission_payload(submission))

    first, second = recorded
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["verdict"] == "approve"
    assert first["findings"] == []
