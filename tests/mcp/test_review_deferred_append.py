"""Publish-path deferred section append (RC2, D1, D3) — W1 RED suite."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.support.tool_context import bind_review_publication_scope, github_client_from_ctx

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.review import create_pull_request_review_tool
from mergecraft.mcp.tool_state import AnalyzerRunState, init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.review_taxonomy import (
    FINDING_MARKER_PREFIX,
    finding_fingerprint,
)
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

DEFERRED_SECTION_HEADING = "### 🗂 Deferred findings"
FIX_ALL_DEFERRED_HEADING = "## Deferred (non-blocking)"


class _RecordingGitHub(GitHubClient):
    """Captures the review payload instead of sending it."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.review_payload: dict[str, Any] = {}

    async def create_review(
        self, owner: str, repo: str, pull_number: int, **payload: Any
    ) -> dict[str, Any]:
        self.review_payload = payload
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


def _deferred_overflow_section(*, path: str, body: str) -> str:
    return (
        f"{DEFERRED_SECTION_HEADING}\n\n"
        "<details><summary>Non-blocking deferred findings</summary>\n\n"
        f"**Major** `{path}:9` — {body}\n\n"
        "</details>"
    )


def _seed_deferred_analyzer_run(
    ctx: ToolContext,
    *,
    path: str = "src/deferred_only.py",
    body: str = "Unchecked null dereference in handler",
) -> str:
    deferred_section = _deferred_overflow_section(path=path, body=body)
    run_kwargs: dict[str, Any] = {
        "ran": True,
        "findings": [
            {
                "path": path,
                "severity": "Major",
                "body": body,
                "fingerprint": finding_fingerprint(path=path, body=body),
            }
        ],
        "deferred_findings": [
            {
                "path": path,
                "line": 9,
                "body": body,
                "severity": "Major",
                "fingerprint": finding_fingerprint(path=path, body=body),
            }
        ],
        "mechanical_section": "### 🔧 Mechanical findings",
    }
    if "deferred_section" in AnalyzerRunState.__dataclass_fields__:
        run_kwargs["deferred_section"] = deferred_section
    ctx.tool_state.analyzer_run = AnalyzerRunState(**run_kwargs)
    return deferred_section


def _inline_comments_for_budget() -> list[dict[str, Any]]:
    return [
        {
            "path": f"src/inline{i:02d}.py",
            "line": i,
            "body": f"_Maintainability & Code Quality_ | _Major_ | _Quick win_ | _likely_\n\nInline {i}.",
        }
        for i in range(1, 9)
    ]


@pytest.mark.asyncio
async def test_publish_appends_deferred_section_without_agent_action(ctx: ToolContext) -> None:
    """RC2 / D3: publish path appends deferred overflow; the agent must not paste it."""
    deferred_body = "Unchecked null dereference in handler"
    deferred_path = "src/deferred_only.py"
    _seed_deferred_analyzer_run(ctx, path=deferred_path, body=deferred_body)
    agent_body = "**Reviewed changes** — summary only.\n\n- **Change** — no deferred paste."
    assert DEFERRED_SECTION_HEADING not in agent_body

    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": agent_body,
            "comments": _inline_comments_for_budget(),
        }
    )

    published_body = str(github_client_from_ctx(ctx).review_payload.get("body") or "")
    assert DEFERRED_SECTION_HEADING in published_body
    assert deferred_body in published_body


@pytest.mark.asyncio
async def test_deferred_section_is_collapsed_and_marked_non_blocking(ctx: ToolContext) -> None:
    _seed_deferred_analyzer_run(ctx)
    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": "Review body without deferred paste.",
            "comments": _inline_comments_for_budget(),
        }
    )
    published_body = str(github_client_from_ctx(ctx).review_payload.get("body") or "")
    assert DEFERRED_SECTION_HEADING in published_body
    assert "<details>" in published_body
    assert "non-blocking" in published_body.casefold()


@pytest.mark.asyncio
async def test_no_inline_comment_is_created_for_a_deferred_finding(ctx: ToolContext) -> None:
    """D1 invariant: deferred overflow never earns an inline anchor."""
    deferred_path = "src/deferred_only.py"
    ctx.tool_state.analyzer_run = AnalyzerRunState(
        ran=True,
        findings=[{"path": deferred_path, "severity": "Major", "body": "deferred only"}],
    )
    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": "Review body without deferred paste.",
            "comments": _inline_comments_for_budget(),
        }
    )
    inline = list(github_client_from_ctx(ctx).review_payload.get("comments") or [])
    inline_paths = {str(row["path"]) for row in inline}
    assert deferred_path not in inline_paths


@pytest.mark.asyncio
async def test_deferred_findings_are_fingerprint_stamped(ctx: ToolContext) -> None:
    """Convention 5: deferred findings carry the same fingerprint marker as inline comments."""
    deferred_path = "src/deferred_only.py"
    deferred_body = "Unchecked null dereference in handler"
    _seed_deferred_analyzer_run(ctx, path=deferred_path, body=deferred_body)
    expected = finding_fingerprint(path=deferred_path, body=deferred_body)

    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": "Review body without deferred paste.",
            "comments": _inline_comments_for_budget(),
        }
    )

    published_body = str(github_client_from_ctx(ctx).review_payload.get("body") or "")
    assert f"{FINDING_MARKER_PREFIX}{expected} -->" in published_body


@pytest.mark.asyncio
async def test_deferred_findings_appear_in_the_fix_all_brief_under_their_own_heading(
    ctx: ToolContext,
) -> None:
    """X3 / W1.2d-bis: Fix-all brief lists deferred findings under a distinct heading."""
    deferred_path = "src/deferred_only.py"
    deferred_body = "Unchecked null dereference in handler"
    _seed_deferred_analyzer_run(ctx, path=deferred_path, body=deferred_body)
    agent_body = (
        "**Reviewed changes** — summary only.\n\n"
        "### 🤖 Fix all findings\n\n"
        "<details><summary>Machine-readable brief for a fix-agent</summary>\n\n"
        "````markdown\n"
        "Verify each finding against current code.\n"
        "\n"
        f"## `{deferred_path}`\n"
        "- L9 — inline-only outcome\n"
        "````\n\n"
        "</details>"
    )

    spec = create_pull_request_review_tool(ctx)
    await spec.execute(
        {
            "pull_number": 7,
            "body": agent_body,
            "comments": _inline_comments_for_budget(),
        }
    )

    published_body = str(github_client_from_ctx(ctx).review_payload.get("body") or "")
    assert "### 🤖 Fix all findings" in published_body
    assert FIX_ALL_DEFERRED_HEADING in published_body
    assert deferred_body in published_body
