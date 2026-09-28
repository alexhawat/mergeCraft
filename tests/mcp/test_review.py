"""Tests for create_pull_request_review inline-comment assembly."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from tests.support.publication import (
    RecordingReviewGitHub,
    finding,
    publication_ctx,
    review_thread,
    submit_verdict,
    unified_diff,
)
from tests.support.tool_context import (
    bind_github_client,
    bind_review_publication_scope,
    github_client_from_ctx,
    write_capable_mcp_mode,
)

from mergecraft.agents.shared import AgentResult
from mergecraft.main_outcome import _classify_outcome
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool, format_analyzer_inline_body
from mergecraft.mcp.tool_state import init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import (
    FINDING_MARKER_PREFIX,
    finding_fingerprint,
    stamp_finding_fingerprint,
)
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.github import GitHubClient


class _RecordingGitHub(GitHubClient):
    """GitHub client that captures the review payload instead of sending it."""

    def __init__(self, *, approve_rejected: bool = False) -> None:
        super().__init__(token="test-token")
        self.review_payload: dict[str, Any] = {}
        self.review_payloads: list[dict[str, Any]] = []
        self.approve_rejected = approve_rejected

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payload = payload
        self.review_payloads.append(payload)
        if self.approve_rejected and payload.get("event") == "APPROVE":
            request = httpx.Request("POST", "https://api.github.com/reviews")
            response = httpx.Response(422, request=request, json={"message": "Unprocessable"})
            raise httpx.HTTPStatusError("422", request=request, response=response)
        return {"id": 1, "node_id": "n1", "html_url": "https://x/1", "state": "COMMENTED"}


class _FailThenSucceedGitHub(_RecordingGitHub):
    """Fail a configured number of publication attempts, then return a receipt."""

    def __init__(self, *, failures: int = 1, invalid_receipt: bool = False) -> None:
        super().__init__()
        self.failures = failures
        self.invalid_receipt = invalid_receipt

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payload = payload
        self.review_payloads.append(payload)
        if self.failures:
            self.failures -= 1
            raise RuntimeError("temporary publication failure")
        if self.invalid_receipt:
            return {"id": "not-an-integer", "node_id": "bad"}
        return {
            "id": 42,
            "node_id": "n42",
            "html_url": "https://x/42",
            "state": payload.get("event") or "COMMENTED",
        }


def _ctx(tmp_path: Path) -> ToolContext:
    tool_ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=_RecordingGitHub(),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )
    bind_review_publication_scope(tool_ctx)
    return tool_ctx


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
    return _ctx(tmp_path)


async def _submit(ctx: ToolContext, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spec = create_pull_request_review_tool(ctx)
    await spec.execute({"pull_number": 7, "body": "review body", "comments": comments})
    payload = github_client_from_ctx(ctx).review_payload  # type: ignore[attr-defined]
    return list(payload.get("comments") or [])


@pytest.mark.asyncio
async def test_publication_retry_clears_unresolved_failure_after_storing_receipt(
    tmp_path: Path,
) -> None:
    github = _FailThenSucceedGitHub()
    tool_ctx = _ctx(tmp_path)
    bind_review_publication_scope(tool_ctx, checkout_sha="abc123")
    bind_github_client(tool_ctx, github)
    tool = create_pull_request_review_tool(tool_ctx)
    params = {"pull_number": 7, "body": "Looks good.", "approved": True}

    first = await tool.execute(params)
    assert first.is_error is True
    assert tool_ctx.tool_state.terminal_publication_failed is True
    assert tool_ctx.tool_state.review is None

    second = await tool.execute(params)
    assert second.is_error is False
    assert tool_ctx.tool_state.review is not None
    assert tool_ctx.tool_state.review.id == 42
    assert tool_ctx.tool_state.review.reviewed_sha == "abc123"
    assert tool_ctx.tool_state.terminal_publication_failed is False

    outcome, reason = _classify_outcome(
        result=AgentResult(success=True, terminal_submission_received=True),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode="Review",
        terminal_publication_failed=tool_ctx.tool_state.terminal_publication_failed,
    )
    assert outcome is RunOutcome.passed
    assert reason is None


@pytest.mark.asyncio
async def test_publication_retry_keeps_failure_until_receipt_is_parseable(tmp_path: Path) -> None:
    github = _FailThenSucceedGitHub(failures=1, invalid_receipt=True)
    tool_ctx = _ctx(tmp_path)
    bind_review_publication_scope(tool_ctx, checkout_sha="abc123")
    bind_github_client(tool_ctx, github)
    tool = create_pull_request_review_tool(tool_ctx)
    params = {"pull_number": 7, "body": "Looks good.", "approved": True}

    assert (await tool.execute(params)).is_error is True
    assert (await tool.execute(params)).is_error is True
    assert tool_ctx.tool_state.review is None
    assert tool_ctx.tool_state.terminal_publication_failed is True


@pytest.mark.asyncio
async def test_repeated_publication_failures_remain_inconclusive(tmp_path: Path) -> None:
    github = _FailThenSucceedGitHub(failures=2)
    tool_ctx = _ctx(tmp_path)
    bind_review_publication_scope(tool_ctx, checkout_sha="abc123")
    bind_github_client(tool_ctx, github)
    tool = create_pull_request_review_tool(tool_ctx)
    params = {"pull_number": 7, "body": "Looks good.", "approved": True}

    assert (await tool.execute(params)).is_error is True
    assert (await tool.execute(params)).is_error is True
    assert tool_ctx.tool_state.review is None
    assert tool_ctx.tool_state.terminal_publication_failed is True

    outcome, reason = _classify_outcome(
        result=AgentResult(success=True, terminal_submission_received=True),
        setup_reason="",
        setup_policy="warn",
        prep_reason=None,
        mode="Review",
        terminal_publication_failed=tool_ctx.tool_state.terminal_publication_failed,
    )
    assert outcome is RunOutcome.inconclusive
    assert reason is not None
    assert "never published" in reason


@pytest.mark.asyncio
async def test_matching_publication_replay_clears_stale_failure_after_scope_check(
    tmp_path: Path,
) -> None:
    github = _FailThenSucceedGitHub(failures=0)
    tool_ctx = _ctx(tmp_path)
    bind_review_publication_scope(tool_ctx, checkout_sha="abc123")
    bind_github_client(tool_ctx, github)
    tool = create_pull_request_review_tool(tool_ctx)
    params = {"pull_number": 7, "body": "Looks good.", "approved": True}
    assert (await tool.execute(params)).is_error is False
    assert len(github.review_payloads) == 1

    tool_ctx.tool_state.terminal_publication_failed = True
    replay = await tool.execute(params)
    assert replay.is_error is False
    assert tool_ctx.tool_state.terminal_publication_failed is False
    assert len(github.review_payloads) == 1

    tool_ctx.tool_state.terminal_publication_failed = True
    wrong_scope = await tool.execute({**params, "commit_id": "wrong-head"})
    assert wrong_scope.is_error is True
    assert tool_ctx.tool_state.terminal_publication_failed is True
    assert len(github.review_payloads) == 1


@pytest.mark.asyncio
async def test_inline_comments_are_fingerprinted(ctx: ToolContext) -> None:
    inline = await _submit(ctx, [{"path": "src/app.py", "line": 12, "body": "A finding."}])
    expected = finding_fingerprint(path="src/app.py", body="A finding.")
    assert "A finding." in inline[0]["body"]
    assert f"{FINDING_MARKER_PREFIX}{expected} -->" in inline[0]["body"]


@pytest.mark.asyncio
async def test_inline_comments_include_batch_resolved_short_id(ctx: ToolContext) -> None:
    """Production PR inline comments surface ``MC-…`` ids for human quoting."""
    from mergecraft.analyzers.finding import finding_short_id

    body = "Unchecked null before return."
    path = "src/util.py"
    inline = await _submit(ctx, [{"path": path, "line": 4, "body": body}])
    fingerprint = finding_fingerprint(path=path, body=body)
    short_id = finding_short_id(fingerprint)
    assert short_id in inline[0]["body"]


@pytest.mark.asyncio
async def test_analyzer_inline_body_keeps_single_short_id_and_fingerprint(
    ctx: ToolContext,
) -> None:
    """Analyzer inline bodies already stamped with ``MC-…`` must not double-prefix."""
    from mergecraft.analyzers.finding import make_finding, resolve_finding_short_ids

    finding = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="src/demo.py",
        start_line=3,
        end_line=3,
        source="analyzer",
    )
    short_ids = resolve_finding_short_ids([finding.fingerprint])
    short_id = short_ids[finding.fingerprint]
    body = format_analyzer_inline_body(finding, short_id=short_id)
    inline = await _submit(
        ctx,
        [
            {
                "path": finding.path,
                "line": finding.start_line,
                "body": body,
                "fingerprint": finding.fingerprint,
            }
        ],
    )
    published = inline[0]["body"]
    assert published.count(f"**{short_id}**") == 1
    assert f"{FINDING_MARKER_PREFIX}{finding.fingerprint} -->" in published
    assert len(re.findall(r"MC-[0-9a-f]{6,}", published)) == 1


@pytest.mark.asyncio
async def test_analyzer_inline_body_nested_finding_fingerprint_is_preserved(
    ctx: ToolContext,
) -> None:
    """Nested ``finding.fingerprint`` wins over body-derived hashing at publish."""
    from mergecraft.analyzers.finding import make_finding, resolve_finding_short_ids

    finding = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="unused import",
        path="src/demo.py",
        start_line=3,
        end_line=3,
        source="analyzer",
    )
    short_ids = resolve_finding_short_ids([finding.fingerprint])
    short_id = short_ids[finding.fingerprint]
    body = format_analyzer_inline_body(finding, short_id=short_id)
    inline = await _submit(
        ctx,
        [
            {
                "path": finding.path,
                "line": finding.start_line,
                "body": body,
                "finding": {"fingerprint": finding.fingerprint},
            }
        ],
    )
    published = inline[0]["body"]
    assert published.count(f"**{short_id}**") == 1
    assert f"{FINDING_MARKER_PREFIX}{finding.fingerprint} -->" in published


@pytest.mark.asyncio
async def test_mixed_source_collision_refreshes_pre_rendered_analyzer_short_id(
    ctx: ToolContext,
) -> None:
    """Agent + analyzer inline comments share one publish batch for ``MC-…`` ids."""
    from tests.analyzers.support_short_id import collision_fingerprints

    from mergecraft.analyzers.finding import (
        finding_short_id,
        make_finding,
        resolve_finding_short_ids,
    )
    from mergecraft.review.finding_lookup import fingerprint_for_short_id

    fp1, fp2 = collision_fingerprints()
    analyzer_finding = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="likely",
        message="Analyzer finding with collision.",
        path="src/analyzer.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        fingerprint=fp2,
    )
    pre_rendered = finding_short_id(fp2)
    analyzer_body = format_analyzer_inline_body(analyzer_finding, short_id=pre_rendered)
    inline = await _submit(
        ctx,
        [
            {
                "path": "src/agent.py",
                "line": 1,
                "body": "Agent finding with collision.",
                "fingerprint": fp1,
            },
            {
                "path": analyzer_finding.path,
                "line": analyzer_finding.start_line,
                "body": analyzer_body,
                "fingerprint": fp2,
            },
        ],
    )
    expected = resolve_finding_short_ids([fp1, fp2])
    assert expected[fp1] != expected[fp2]
    analyzer_published = inline[1]["body"]
    assert f"**{expected[fp2]}**" in analyzer_published
    assert f"**{pre_rendered}**" not in analyzer_published
    assert fingerprint_for_short_id(expected[fp2], (fp1, fp2)) == fp2
    assert len(re.findall(r"MC-[0-9a-f]{6,}", analyzer_published)) == 1


@pytest.mark.asyncio
async def test_mixed_source_collision_refreshes_title_path_short_id(
    ctx: ToolContext,
) -> None:
    """Title-path agent comments also pick up batch-resolved ``MC-…`` ids."""
    from tests.analyzers.support_short_id import collision_fingerprints

    from mergecraft.analyzers.finding import (
        finding_short_id,
        make_finding,
        render_finding_pr_comment,
        resolve_finding_short_ids,
    )

    fp1, fp2 = collision_fingerprints()
    agent_finding = make_finding(
        tool="mergecraft",
        rule_id="logic",
        category="Functional Correctness",
        severity="Major",
        confidence="likely",
        message="Agent finding with collision.",
        path="src/agent.py",
        start_line=1,
        end_line=1,
        source="agent",
        fingerprint=fp2,
    )
    pre_rendered = finding_short_id(fp2)
    agent_body = render_finding_pr_comment(agent_finding, short_id=pre_rendered)
    inline = await _submit(
        ctx,
        [
            {
                "path": agent_finding.path,
                "line": agent_finding.start_line,
                "body": agent_body,
                "fingerprint": fp2,
            },
            {
                "path": "src/other.py",
                "line": 2,
                "body": "Second finding forces collision resolution.",
                "fingerprint": fp1,
            },
        ],
    )
    expected = resolve_finding_short_ids([fp1, fp2])
    agent_published = inline[0]["body"]
    assert agent_published.startswith(f"**{expected[fp2]}**")
    assert f"**{pre_rendered}**" not in agent_published
    assert len(re.findall(r"MC-[0-9a-f]{6,}", agent_published)) == 1


@pytest.mark.asyncio
async def test_body_only_analyzer_collision_refreshes_mechanical_short_id(
    ctx: ToolContext,
) -> None:
    """Body-only analyzer + agent inline share one publish batch for ``MC-…`` ids."""
    from tests.analyzers.support_short_id import collision_fingerprints
    from tests.support.tool_context import github_client_from_ctx

    from mergecraft.analyzers.budget import place_findings
    from mergecraft.analyzers.finding import (
        finding_short_id,
        make_finding,
        resolve_finding_short_ids,
    )
    from mergecraft.mcp.tool_state import AnalyzerRunState
    from mergecraft.review.finding_lookup import fingerprint_for_short_id

    fp1, fp2 = collision_fingerprints()
    inline_finding = make_finding(
        tool="actionlint",
        rule_id="inline",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="likely",
        message="inline collision",
        path="src/inline.py",
        start_line=1,
        end_line=1,
        source="analyzer",
        fingerprint=fp1,
    )
    mechanical_finding = make_finding(
        tool="actionlint",
        rule_id="overflow",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="likely",
        message="mechanical collision",
        path="src/mechanical.py",
        start_line=2,
        end_line=2,
        source="analyzer",
        fingerprint=fp2,
    )
    placement = place_findings([inline_finding, mechanical_finding], inline_budget=1)
    pre_rendered = finding_short_id(fp2)

    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[inline_finding.model_dump(), mechanical_finding.model_dump()],
        mechanical_section=placement.mechanical_section,
        deferred_findings=[],
    )

    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": "Review body.",
            "comments": [
                {
                    "path": "src/agent.py",
                    "line": 1,
                    "body": "Agent finding with collision.",
                    "fingerprint": fp1,
                }
            ],
        }
    )

    payload = github_client_from_ctx(ctx).review_payload  # type: ignore[attr-defined]
    published_body = str(payload.get("body") or "")
    expected = resolve_finding_short_ids([fp1, fp2])
    assert expected[fp1] != expected[fp2]
    assert f"**{expected[fp2]}**" in published_body
    assert f"**{pre_rendered}**" not in published_body
    assert fingerprint_for_short_id(expected[fp2], (fp1, fp2)) == fp2

    inline = list(payload.get("comments") or [])
    assert f"**{expected[fp1]}**" in inline[0]["body"]
    assert fingerprint_for_short_id(expected[fp1], (fp1, fp2)) == fp1


@pytest.mark.asyncio
async def test_identical_findings_share_a_fingerprint(ctx: ToolContext) -> None:
    inline = await _submit(
        ctx,
        [
            {"path": "src/app.py", "line": 12, "body": "A finding."},
            {"path": "src/app.py", "line": 40, "body": "A  finding."},
            {"path": "src/other.py", "line": 12, "body": "A finding."},
        ],
    )
    first, reworded, other_path = (c["body"] for c in inline)
    marker = f"{FINDING_MARKER_PREFIX}{finding_fingerprint(path='src/app.py', body='A finding.')}"
    assert marker in first
    assert marker in reworded
    assert marker not in other_path


@pytest.mark.asyncio
@pytest.mark.asyncio
async def test_approve_422_falls_back_to_comment_and_keeps_approval(tmp_path: Path) -> None:
    github = _RecordingGitHub(approve_rejected=True)
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=github,
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
    bind_review_publication_scope(ctx)
    spec = create_pull_request_review_tool(ctx)
    result = await spec.execute(
        {"pull_number": 7, "body": "Looks good.", "approved": True},
    )
    assert result.is_error is False
    payload_text = result.content[0]["text"]
    assert "approveFallbackDueTo422" in payload_text
    assert github.review_payloads[0]["event"] == "APPROVE"
    assert github.review_payloads[1]["event"] == "COMMENT"
    assert ctx.tool_state.approval is not None
    assert ctx.tool_state.approval.would_approve is True


class _ThreadGitHub(_RecordingGitHub):
    """Adds review-thread reads and resolve mutations to the recording client."""

    def __init__(self, threads: list[dict[str, Any]]) -> None:
        super().__init__()
        self._threads = threads
        self.resolved: list[str] = []

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        if "resolveReviewThread" in query:
            thread_id = str((variables or {})["threadId"])
            self.resolved.append(thread_id)
            return {"resolveReviewThread": {"thread": {"id": thread_id, "isResolved": True}}}
        return {
            "repository": {"pullRequest": {"reviewThreads": {"nodes": self._threads}}},
        }


def _stale_thread(body: str) -> dict[str, Any]:
    return {
        "id": "T-stale",
        "isResolved": False,
        "isOutdated": True,
        "comments": {
            "nodes": [
                {
                    "databaseId": 11,
                    "body": body,
                    "author": {"login": "mergecraft"},
                    "path": "src/app.py",
                    "line": 3,
                    "originalLine": 3,
                    "createdAt": "2026-01-01T00:00:00Z",
                }
            ]
        },
    }


def _incremental_ctx(
    github: GitHubClient,
    tmp_path: Path,
    changed: list[str],
    *,
    publishers: frozenset[str] = frozenset({"mergecraft"}),
    incremental_diff: str | None = None,
) -> ToolContext:
    """An IncrementalReview re-review bound to PR #7.

    ``publishers`` pre-resolves the run's expected-publisher set (no lookup),
    and ``incremental_diff`` is the patch since the last reviewed commit; by
    default it touches lines 1-5 of every path in ``changed``.
    """
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.selected_mode = "IncrementalReview"
    primary = primary_repo_state(state)
    primary.incremental_changed_paths = changed
    patch = incremental_diff
    if patch is None:
        patch = "".join(unified_diff(path, start=1, count=5) for path in changed)
    incremental_path = tmp_path / "incremental.patch"
    incremental_path.write_text(patch, encoding="utf-8")
    primary.incremental_diff_path = str(incremental_path)
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_synchronize")),
        github=github,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )
    bind_review_publication_scope(ctx)
    ctx.publisher_logins = publishers
    return ctx


@pytest.mark.asyncio
async def test_rereview_resolves_threads_whose_findings_are_gone(tmp_path: Path) -> None:
    stale = stamp_finding_fingerprint(path="src/app.py", body="Old finding.")
    github = _ThreadGitHub([_stale_thread(stale)])
    ctx = _incremental_ctx(github, tmp_path, ["src/app.py"])
    spec = create_pull_request_review_tool(ctx)

    result = await spec.execute(
        {
            "pull_number": 7,
            "body": "re-review",
            "comments": [{"path": "src/app.py", "line": 9, "body": "A different finding."}],
        }
    )

    assert github.resolved == ["T-stale"]
    assert '"resolvedThreads": 1' in result.content[0]["text"]


@pytest.mark.asyncio
async def test_rereview_keeps_threads_for_findings_it_raised_again(tmp_path: Path) -> None:
    stale = stamp_finding_fingerprint(path="src/app.py", body="Old finding.")
    github = _ThreadGitHub([_stale_thread(stale)])
    ctx = _incremental_ctx(github, tmp_path, ["src/app.py"])
    spec = create_pull_request_review_tool(ctx)

    await spec.execute(
        {
            "pull_number": 7,
            "body": "re-review",
            "comments": [{"path": "src/app.py", "line": 3, "body": "Old finding."}],
        }
    )

    assert github.resolved == []


@pytest.mark.asyncio
async def test_full_review_never_resolves_threads(tmp_path: Path) -> None:
    stale = stamp_finding_fingerprint(path="src/app.py", body="Old finding.")
    github = _ThreadGitHub([_stale_thread(stale)])
    ctx = _incremental_ctx(github, tmp_path, ["src/app.py"])
    ctx.tool_state.selected_mode = "Review"
    spec = create_pull_request_review_tool(ctx)

    await spec.execute({"pull_number": 7, "body": "first review"})

    assert github.resolved == []


async def test_suggestion_is_fenced_before_fingerprinting(ctx: ToolContext) -> None:
    inline = await _submit(
        ctx,
        [{"path": "src/app.py", "line": 12, "body": "Parenthesize.", "suggestion": "    pass"}],
    )
    body = inline[0]["body"]
    assert "```suggestion\n    pass\n```" in body
    assert body.index("```suggestion") < body.index(FINDING_MARKER_PREFIX)


@pytest.fixture
def self_review_approval_enabled() -> bool:
    config = yaml.safe_load(
        (Path(__file__).resolve().parents[2] / ".mergecraft/config.yaml").read_text()
    )
    enabled = config["prApproveEnabled"]
    assert isinstance(enabled, bool)
    return enabled


@pytest.mark.parametrize("approval", [{"approved": True}, {"event": "APPROVE"}])
async def test_self_review_config_publishes_comments_before_isolated_approval(
    ctx: ToolContext, approval: dict[str, object], self_review_approval_enabled: bool
) -> None:
    assert self_review_approval_enabled is False
    ctx.pr_approve_enabled = self_review_approval_enabled
    result = await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "Review complete.", **approval}
    )
    assert result.is_error is False
    github = github_client_from_ctx(ctx)
    assert isinstance(github, _RecordingGitHub)
    assert [body["event"] for body in github.review_payloads] == ["COMMENT"]


# ── thread retirement: a touched line, an expected author, a finding gone ─────
#
# A re-review retires a thread only when its anchored line falls inside an
# incremental-diff hunk (or GitHub marks it outdated), every comment's author is
# in the run's expected-publisher set, and none of its fingerprints is still
# raised anywhere in the terminal submission — inline, demoted to the body, or
# deferred. The create-review response's login is never added to the set.

_APP_BOT = "mergecraft-app[bot]"
_OLD = stamp_finding_fingerprint(path="src/app.py", body="Old finding.")


def _rereview_ctx(
    tmp_path: Path,
    *,
    threads: list[dict[str, Any]],
    incremental_diff: str,
    publishers: frozenset[str] = frozenset({_APP_BOT}),
    full_diff: str | None = None,
    reviewer_login: str = _APP_BOT,
) -> tuple[ToolContext, RecordingReviewGitHub]:
    github = RecordingReviewGitHub(threads=threads, reviewer_login=reviewer_login)
    kwargs: dict[str, Any] = {}
    if full_diff is not None:
        kwargs["diff_text"] = full_diff
    ctx = publication_ctx(
        tmp_path, github=github, trust_tier="trusted", mode="IncrementalReview", **kwargs
    )
    primary = primary_repo_state(ctx.tool_state)
    primary.incremental_changed_paths = ["src/app.py"]
    incremental_path = tmp_path / "incremental.patch"
    incremental_path.write_text(incremental_diff, encoding="utf-8")
    primary.incremental_diff_path = str(incremental_path)
    ctx.publisher_logins = publishers
    return ctx, github


async def _post_rereview(ctx: ToolContext, comments: list[dict[str, Any]]) -> Any:
    return await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": "re-review", "comments": comments}
    )


_NEW_COMMENT = {"path": "src/app.py", "line": 12, "body": "A different finding."}


@pytest.mark.asyncio
async def test_rereview_keeps_a_thread_whose_line_no_hunk_touched(tmp_path: Path) -> None:
    """The file changed (lines 40-44), the finding's line (3) did not: the thread stays open."""
    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[review_thread(thread_id="T-line3", body=_OLD, author=_APP_BOT, line=3)],
        incremental_diff=unified_diff("src/app.py", start=40, count=5),
    )
    await _post_rereview(ctx, [_NEW_COMMENT])
    assert github.resolved == []


@pytest.mark.asyncio
async def test_rereview_resolves_a_thread_whose_line_a_hunk_touched(tmp_path: Path) -> None:
    """Green guard: the finding's own line changed and the finding is gone."""
    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[review_thread(thread_id="T-line42", body=_OLD, author=_APP_BOT, line=42)],
        incremental_diff=unified_diff("src/app.py", start=40, count=5),
    )
    await _post_rereview(ctx, [_NEW_COMMENT])
    assert github.resolved == ["T-line42"]


@pytest.mark.asyncio
async def test_rereview_keeps_the_thread_of_a_finding_demoted_to_the_body(tmp_path: Path) -> None:
    """The finding was re-raised, but its anchor is not in the diff, so it went to the body.

    Only the final inline list used to count as "still raised"; a demoted
    finding therefore looked fixed and its thread was closed.
    """
    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[review_thread(thread_id="T-old", body=_OLD, author=_APP_BOT, outdated=True)],
        incremental_diff=unified_diff("src/app.py", start=1, count=5),
        full_diff=unified_diff("src/other.py", start=1, count=5),
    )
    await _post_rereview(ctx, [{"path": "src/app.py", "line": 3, "body": "Old finding."}])

    posted = github.review_payloads[-1]
    assert not posted.get("comments"), "fixture error: the re-raised finding must be demoted"
    assert FINDING_MARKER_PREFIX in str(posted.get("body") or "")
    assert github.resolved == []


@pytest.mark.asyncio
async def test_rereview_keeps_the_thread_of_a_finding_still_in_the_terminal_submission(
    tmp_path: Path,
) -> None:
    """A deferred finding: recorded in the submission, never posted inline, still open."""
    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[review_thread(thread_id="T-old", body=_OLD, author=_APP_BOT, outdated=True)],
        incremental_diff=unified_diff("src/app.py", start=1, count=5),
    )
    await submit_verdict(
        ctx,
        "request_changes",
        [finding("Old finding.", line=3), finding("A different finding.", line=12)],
    )
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    await create_pull_request_review_tool(ctx).execute(
        {"pull_number": 7, "body": submission.summary, "comments": [_NEW_COMMENT]}
    )
    assert github.review_payloads, "fixture error: the re-review must have been posted"
    assert github.resolved == []


@pytest.mark.asyncio
async def test_rereview_keeps_a_marked_thread_by_an_unexpected_author(tmp_path: Path) -> None:
    """The marker is typeable by anyone; the author is not in the publisher set."""
    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[review_thread(thread_id="T-forged", body=_OLD, author="mallory", outdated=True)],
        incremental_diff=unified_diff("src/app.py", start=1, count=5),
    )
    await _post_rereview(ctx, [_NEW_COMMENT])
    assert github.resolved == []


@pytest.mark.parametrize(
    "publishers", [frozenset(), frozenset({_APP_BOT})], ids=["job_token", "app_configured"]
)
@pytest.mark.asyncio
async def test_rereview_never_trusts_the_shared_actions_bot(
    tmp_path: Path, publishers: frozenset[str]
) -> None:
    """The create-review response came from ``github-actions[bot]``; its threads still stay open."""
    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[
            review_thread(
                thread_id="T-actions", body=_OLD, author="github-actions[bot]", outdated=True
            )
        ],
        incremental_diff=unified_diff("src/app.py", start=1, count=5),
        publishers=publishers,
        reviewer_login="github-actions[bot]",
    )
    await _post_rereview(ctx, [_NEW_COMMENT])
    assert github.resolved == []
    assert "github-actions[bot]" not in (ctx.publisher_logins or frozenset())


@pytest.mark.asyncio
async def test_rereview_with_no_expected_publisher_resolves_nothing_and_says_why(
    tmp_path: Path,
) -> None:
    from loguru import logger

    ctx, github = _rereview_ctx(
        tmp_path,
        threads=[review_thread(thread_id="T-app", body=_OLD, author=_APP_BOT, outdated=True)],
        incremental_diff=unified_diff("src/app.py", start=1, count=5),
        publishers=frozenset(),
    )
    captured: list[str] = []
    sink_id = logger.add(lambda message: captured.append(str(message)), level="INFO")
    try:
        result = await _post_rereview(ctx, [_NEW_COMMENT])
    finally:
        logger.remove(sink_id)

    assert result.is_error is False
    assert github.resolved == []
    assert any("publisher" in line.lower() for line in captured), captured


# ── resolve_review_thread fails closed on a missing payload ──────────────────


class _ResolvePayloadGitHub(RecordingReviewGitHub):
    """Answers the resolve mutation with a scripted GraphQL payload."""

    def __init__(self, payload: Any) -> None:
        super().__init__()
        self._payload = payload

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> Any:
        self.graphql_calls.append(query)
        return self._payload


_MALFORMED_RESOLVE_PAYLOADS = [
    pytest.param({}, id="empty"),
    pytest.param(None, id="null"),
    pytest.param({"resolveReviewThread": None}, id="null_mutation"),
    pytest.param({"resolveReviewThread": {"thread": None}}, id="null_thread"),
    pytest.param({"resolveReviewThread": {"thread": {}}}, id="thread_without_state"),
]


@pytest.mark.parametrize("payload", _MALFORMED_RESOLVE_PAYLOADS)
@pytest.mark.asyncio
async def test_resolve_review_thread_treats_a_missing_payload_as_not_resolved(
    tmp_path: Path, payload: Any
) -> None:
    from mergecraft.mcp.review_comments import resolve_review_thread

    ctx = publication_ctx(tmp_path, github=_ResolvePayloadGitHub(payload), trust_tier="trusted")
    assert await resolve_review_thread(ctx, "T1") is False


@pytest.mark.parametrize("state", [True, False])
@pytest.mark.asyncio
async def test_resolve_review_thread_reports_what_github_said(tmp_path: Path, state: bool) -> None:
    """Green guard: a well-formed payload is reported as-is."""
    from mergecraft.mcp.review_comments import resolve_review_thread

    payload = {"resolveReviewThread": {"thread": {"id": "T1", "isResolved": state}}}
    ctx = publication_ctx(tmp_path, github=_ResolvePayloadGitHub(payload), trust_tier="trusted")
    assert await resolve_review_thread(ctx, "T1") is state


@pytest.mark.parametrize("payload", _MALFORMED_RESOLVE_PAYLOADS)
@pytest.mark.asyncio
async def test_resolve_tool_does_not_mark_the_run_updated_on_a_missing_payload(
    tmp_path: Path, payload: Any
) -> None:
    import json

    from mergecraft.mcp.review_comments import resolve_review_thread_tool

    ctx = publication_ctx(tmp_path, github=_ResolvePayloadGitHub(payload), trust_tier="trusted")
    # The MCP tool is default-denied in review-only runs; the internal helper
    # above is what thread retirement calls. The tool's own contract is pinned
    # under a write-capable mode.
    with write_capable_mcp_mode():
        result = await resolve_review_thread_tool(ctx).execute({"thread_id": "T1"})

    assert result.is_error is False
    assert json.loads(result.content[0]["text"])["isResolved"] is False
    assert ctx.tool_state.was_updated is False


@pytest.mark.asyncio
async def test_resolve_tool_marks_the_run_updated_when_github_resolved(tmp_path: Path) -> None:
    """Green guard: a real resolution is still recorded."""
    import json

    from mergecraft.mcp.review_comments import resolve_review_thread_tool

    payload = {"resolveReviewThread": {"thread": {"id": "T1", "isResolved": True}}}
    ctx = publication_ctx(tmp_path, github=_ResolvePayloadGitHub(payload), trust_tier="trusted")
    with write_capable_mcp_mode():
        result = await resolve_review_thread_tool(ctx).execute({"thread_id": "T1"})

    assert result.is_error is False
    assert json.loads(result.content[0]["text"])["isResolved"] is True
    assert ctx.tool_state.was_updated is True
