"""Shared helpers for wave plan 14 — publication & attribution integrity."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import httpx

from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import TerminalSubmission, init_tool_state, primary_repo_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.support.tool_context import bind_github_client, bind_review_publication_scope

if TYPE_CHECKING:
    from pathlib import Path

# W0 #572 probe string (PR #567 round 1).
PROBE_BODY = "test-probe: body only, no inline comments"
PROBE_INLINE_BODY = "test-probe: single comment"


def anchor_422_error(*, index: int | None) -> httpx.HTTPStatusError:
    """Build a GitHub inline-comment anchor 422 matching ``parse_comment_422_index``."""
    request = httpx.Request("POST", "https://api.github.com/reviews")
    errors: list[dict[str, Any]]
    if index is None:
        errors = [{"field": "comments", "code": "invalid"}]
    else:
        errors = [{"field": "comments", "code": "invalid", "index": index}]
    response = httpx.Response(
        422,
        request=request,
        json={"message": "Validation Failed", "errors": errors},
    )
    return httpx.HTTPStatusError("422", request=request, response=response)


class RecordingGitHub(GitHubClient):
    """GitHub client that records review payloads and simulates 422 recovery."""

    def __init__(
        self,
        *,
        approve_rejected: bool = False,
        comment_422_index: int | None = 0,
        comment_422_without_index: bool = False,
        loop_guard: int = 25,
    ) -> None:
        super().__init__(token="test-token")
        self.review_payloads: list[dict[str, Any]] = []
        self.create_review_calls = 0
        self.approve_rejected = approve_rejected
        self.comment_422_index = comment_422_index
        self.comment_422_without_index = comment_422_without_index
        self.loop_guard = loop_guard

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        del owner, repo, pull_number
        self.create_review_calls += 1
        self.review_payloads.append(dict(payload))
        if self.create_review_calls > self.loop_guard:
            msg = f"anchor recovery exceeded loop guard ({self.loop_guard} calls)"
            raise RuntimeError(msg)
        if self.approve_rejected and payload.get("event") == "APPROVE":
            raise anchor_422_error(index=None)
        if payload.get("comments"):
            if self.comment_422_without_index:
                raise anchor_422_error(index=None)
            raise anchor_422_error(index=self.comment_422_index)
        return {
            "id": len(self.review_payloads),
            "node_id": f"n{len(self.review_payloads)}",
            "html_url": f"https://example.test/reviews/{len(self.review_payloads)}",
            "state": str(payload.get("event") or "COMMENTED"),
        }


class RaceGitHub(RecordingGitHub):
    """Replay #572: inline 422, then a body-only probe can win the review slot."""

    def __init__(self) -> None:
        super().__init__(loop_guard=10)
        self.successful_reviews = 0

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        del owner, repo, pull_number
        self.create_review_calls += 1
        self.review_payloads.append(dict(payload))
        body = str(payload.get("body") or "")
        if payload.get("comments"):
            raise anchor_422_error(index=0)
        if PROBE_BODY in body:
            self.successful_reviews += 1
            return {
                "id": 5059373841,
                "node_id": "n-probe",
                "html_url": "https://example.test/reviews/probe",
                "state": "CHANGES_REQUESTED",
            }
        if "Real findings" in body or "demoted inline finding" in body.lower():
            self.successful_reviews += 1
            return {
                "id": 5059373842,
                "node_id": "n-real",
                "html_url": "https://example.test/reviews/real",
                "state": str(payload.get("event") or "COMMENTED"),
            }
        raise anchor_422_error(index=None)


def publication_ctx(
    tmp_path: Path,
    *,
    github: GitHubClient | None = None,
    checkout_sha: str = "e656debc",
    pr_number: int = 7,
) -> ToolContext:
    """ToolContext with publication scope, settings snapshot, and diff."""
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    client = github or RecordingGitHub()
    tool_ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request", issue_number=pr_number, is_pr=True),
            shell="restricted",
        ),
        github=client,
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        pr_approve_enabled=True,
        trust_tier="trusted",
        repo_settings_snapshot=snapshot,
    )
    bind_github_client(tool_ctx, client)
    bind_review_publication_scope(tool_ctx, pr_number=pr_number, checkout_sha=checkout_sha)
    diff_path = tmp_path / "diff.patch"
    diff_path.write_text(
        "diff --git a/src/in_diff.py b/src/in_diff.py\n@@ -8,3 +8,4 @@\n context\n+added\n",
        encoding="utf-8",
    )
    primary_repo_state(tool_ctx.tool_state).diff_path = str(diff_path)
    return tool_ctx


def bind_terminal_submission(
    ctx: ToolContext,
    *,
    summary: str,
    verdict: str = "request_changes",
    findings: list[dict[str, Any]] | None = None,
) -> TerminalSubmission:
    """Attach a validated terminal submission for publication tests."""
    submission = TerminalSubmission(
        id="terminal-sub-1",
        verdict=verdict,  # type: ignore[arg-type]
        summary=summary,
        findings=findings or [],
        payload_hash="hash-terminal-sub-1",
        submitted_at="2026-08-30T00:00:00Z",
        attempt_id=1,
    )
    ctx.tool_state.terminal_submission = submission
    return submission


def two_reviewer_registry() -> object:
    """Minimal two-reviewer registry for attribution tests."""
    from mergecraft.agents.registry import AgentBinding, AgentRole, Registry

    primary = AgentBinding(
        agent_id="mergecraft-reviewer",
        role=AgentRole.reviewer,
        model_chain=("anthropic/claude-sonnet",),
        prompt_id="mergecraft.reviewer",
        prompt_version="1.0.0",
        tool_classes=frozenset(),
        budget=8,
        timeout_s=600,
    )
    secondary = AgentBinding(
        agent_id="reviewer2",
        role=AgentRole.reviewer,
        model_chain=("openai/gpt-5.3-codex",),
        prompt_id="mergecraft.reviewer",
        prompt_version="1.0.0",
        tool_classes=frozenset(),
        budget=8,
        timeout_s=600,
    )
    return Registry({"reviewer": primary, "reviewer2": secondary})
