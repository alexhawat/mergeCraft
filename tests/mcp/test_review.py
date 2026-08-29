"""Tests for create_pull_request_review inline-comment assembly."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

import httpx
import pytest
from tests.support.tool_context import bind_review_publication_scope, github_client_from_ctx

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
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


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


@pytest.fixture
def ctx(tmp_path: Path) -> ToolContext:
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
    )
    bind_review_publication_scope(tool_ctx)
    return tool_ctx


async def _submit(ctx: ToolContext, comments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    spec = create_pull_request_review_tool(ctx)
    await spec.execute({"pull_number": 7, "body": "review body", "comments": comments})
    payload = github_client_from_ctx(ctx).review_payload  # type: ignore[attr-defined]
    return list(payload.get("comments") or [])


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


def _incremental_ctx(github: GitHubClient, tmp_path: Path, changed: list[str]) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.selected_mode = "IncrementalReview"
    primary_repo_state(state).incremental_changed_paths = changed
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
    )
    bind_review_publication_scope(ctx)
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
