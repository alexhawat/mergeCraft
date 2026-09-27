"""Hermetic fakes for the review-publication and thread-retirement suites.

``RecordingReviewGitHub`` answers every call the publisher and the thread
retirement pass make without touching the network: reviews and issue comments
list empty, ``create_review`` records its payload and returns a numbered
receipt, and GraphQL serves a configured thread list and records resolve
mutations. ``publication_ctx`` binds a Review run to PR #7 at a fixed head with
a real unified diff for ``src/app.py``, so findings on that path anchor inline.

Every context built here passes ``trust_tier`` explicitly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

import httpx

from mergecraft.agents.shared import AgentRunContext, ResolvedInstructions
from mergecraft.mcp.tool_state import primary_repo_state
from mergecraft.review_resolution import finding_fingerprints_in
from mergecraft.utils.github import GitHubClient
from tests.support.tool_context import bind_review_publication_scope, make_tool_context

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext
    from mergecraft.mcp.shared import ToolResult

HEAD_SHA = "abc123"
PR_NUMBER = 7

# A full-PR diff whose single hunk covers lines 1-60 of ``src/app.py`` on the
# RIGHT side, so any finding on that file at those lines anchors inline.
APP_DIFF = (
    "diff --git a/src/app.py b/src/app.py\n"
    "--- a/src/app.py\n"
    "+++ b/src/app.py\n"
    "@@ -1,60 +1,60 @@\n" + "".join(f" line {n}\n" for n in range(1, 61))
)


def unified_diff(path: str, *, start: int, count: int) -> str:
    """Return a one-hunk unified diff that adds ``count`` lines at ``start`` of ``path``."""
    body = "".join(f"+added {n}\n" for n in range(start, start + count))
    return (
        f"diff --git a/{path} b/{path}\n"
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        f"@@ -{start},0 +{start},{count} @@\n{body}"
    )


class RecordingReviewGitHub(GitHubClient):
    """GitHub client that records review POSTs and resolve mutations, offline."""

    def __init__(
        self,
        *,
        threads: list[dict[str, Any]] | None = None,
        reviewer_login: str = "mergecraft-app[bot]",
        create_failures: int = 0,
    ) -> None:
        super().__init__(token="test-token")
        self.review_payloads: list[dict[str, Any]] = []
        self.resolved: list[str] = []
        self.graphql_calls: list[str] = []
        self._threads = list(threads or [])
        self._reviewer_login = reviewer_login
        self._create_failures = create_failures

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        del owner, repo, pull_number
        self.review_payloads.append(dict(payload))
        if self._create_failures:
            self._create_failures -= 1
            request = httpx.Request("POST", "https://api.github.com/repos/acme/demo/pulls/7")
            response = httpx.Response(500, request=request, json={"message": "Server Error"})
            raise httpx.HTTPStatusError("500", request=request, response=response)
        review_id = len(self.review_payloads)
        return {
            "id": review_id,
            "node_id": f"n{review_id}",
            "html_url": f"https://github.com/acme/demo/pull/7#review-{review_id}",
            "state": payload.get("event") or "COMMENTED",
            "user": {"login": self._reviewer_login},
            "commit_id": payload.get("commit_id"),
        }

    async def list_issue_comments(
        self, owner: str, repo: str, issue_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        del owner, repo, issue_number, kwargs
        return []

    async def list_reviews(
        self, owner: str, repo: str, pull_number: int, **kwargs: Any
    ) -> list[dict[str, Any]]:
        del owner, repo, pull_number, kwargs
        return []

    async def get(self, path: str, **kwargs: Any) -> Any:
        del path, kwargs
        return {}

    async def graphql(self, query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        self.graphql_calls.append(query)
        if "resolveReviewThread" in query:
            thread_id = str((variables or {})["threadId"])
            self.resolved.append(thread_id)
            return {"resolveReviewThread": {"thread": {"id": thread_id, "isResolved": True}}}
        return {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {"totalCount": len(self._threads), "nodes": self._threads}
                }
            }
        }


def review_thread(
    *,
    thread_id: str,
    body: str,
    author: str,
    path: str = "src/app.py",
    line: int = 3,
    outdated: bool = False,
    resolved: bool = False,
) -> dict[str, Any]:
    """Return one GraphQL ``reviewThreads`` node in the shape GitHub sends."""
    return {
        "id": thread_id,
        "isResolved": resolved,
        "isOutdated": outdated,
        "comments": {
            "totalCount": 1,
            "nodes": [
                {
                    "databaseId": 11,
                    "body": body,
                    "author": {"login": author},
                    "path": path,
                    "line": None if outdated else line,
                    "originalLine": line,
                    "url": f"https://github.com/acme/demo/pull/7#discussion_r{thread_id}",
                    "createdAt": "2026-01-01T00:00:00Z",
                }
            ],
        },
    }


def publication_ctx(
    tmp_path: Path,
    *,
    github: GitHubClient,
    trust_tier: Literal["trusted", "untrusted"],
    mode: str = "Review",
    diff_text: str = APP_DIFF,
    pr_approve_enabled: bool = False,
) -> ToolContext:
    """Return a Review/IncrementalReview context bound to PR #7 at ``HEAD_SHA``."""
    ctx = make_tool_context(
        tmp_path,
        trust_tier=trust_tier,
        github=github,
        pr_approve_enabled=pr_approve_enabled,
    )
    bind_review_publication_scope(ctx, pr_number=PR_NUMBER, checkout_sha=HEAD_SHA)
    ctx.tool_state.selected_mode = mode
    ctx.tool_state.trust_tier = trust_tier
    ctx.tool_state.authority_trust = trust_tier
    primary = primary_repo_state(ctx.tool_state)
    assert primary.diff_path is not None
    (tmp_path / "diff.patch").write_text(diff_text, encoding="utf-8")
    return ctx


def run_ctx_for(ctx: ToolContext) -> AgentRunContext:
    """Return the ``AgentRunContext`` ``finalize_agent_result`` reads."""
    return AgentRunContext(
        payload=ctx.payload,
        mcp_server_url=ctx.mcp_server_url,
        tmpdir=ctx.tmpdir,
        subagent_denied_tools=(),
        instructions=ResolvedInstructions(),
        tool_state=ctx.tool_state,
    )


def finding(body: str, *, line: int = 12, path: str = "src/app.py") -> dict[str, Any]:
    """Return one ``AgentFinding``-shaped row for ``submit_review_verdict``."""
    return {"path": path, "line": line, "severity": "Major", "body": body}


async def submit_verdict(
    ctx: ToolContext,
    verdict: Literal["approve", "request_changes"],
    findings: list[dict[str, Any]] | None = None,
    *,
    summary: str | None = None,
) -> ToolResult:
    """Record a terminal verdict through the real tool; a rejection is a fixture error."""
    from mergecraft.mcp.verdict import submit_review_verdict_tool

    payload = {
        "verdict": verdict,
        "summary": summary or f"Terminal verdict: {verdict}.",
        "findings": list(findings or []),
    }
    result: ToolResult = await submit_review_verdict_tool(ctx).execute(payload)
    assert result.is_error is False, (
        f"fixture error: submit_review_verdict rejected {verdict}: {result.content[0]['text']}"
    )
    return result


def submission_fingerprints(ctx: ToolContext) -> set[str]:
    """Fingerprints of the recorded terminal submission's findings."""
    submission = ctx.tool_state.terminal_submission
    assert submission is not None
    fingerprints: set[str] = set()
    for item in submission.findings:
        identity = getattr(item, "identity", None)
        if callable(identity):
            fingerprints.add(str(identity()))
        elif isinstance(item, dict) and item.get("fingerprint"):
            fingerprints.add(str(item["fingerprint"]))
    return fingerprints


def inline_fingerprints(payload: dict[str, Any]) -> set[str]:
    """Fingerprints stamped into a posted review's inline comments."""
    found: set[str] = set()
    for comment in payload.get("comments") or []:
        found |= finding_fingerprints_in(str(comment.get("body") or ""))
    return found


__all__ = [
    "APP_DIFF",
    "HEAD_SHA",
    "PR_NUMBER",
    "RecordingReviewGitHub",
    "finding",
    "inline_fingerprints",
    "publication_ctx",
    "review_thread",
    "run_ctx_for",
    "submission_fingerprints",
    "submit_verdict",
    "unified_diff",
]
