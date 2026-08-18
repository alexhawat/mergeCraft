"""DG9.1 RED suite — ``ScmProvider`` protocol contract (D10).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (DG9.1 RED,
DG9.2 impl). Six tests are ``@pytest.mark.xfail(strict=False)`` pending protocol
extraction; ``test_github_adapter_behaviour_is_unchanged`` is the pre-refactor
behavioural snapshot that must keep passing through DG9.2.

Pinned contracts (W0):
    D10 — protocol before adapters; GitHub reimplemented as the first adapter
          with no behaviour change.
    G16 — GitHub is the only SCM today; extraction must not regress MCP tools.
"""

from __future__ import annotations

import dataclasses
import importlib
import inspect
import json
from pathlib import Path
from typing import Any

import pytest
from tests.scm.conftest import (
    _DG9_2_XFAIL,
    RecordingGitHubClient,
    github_snapshot_transport,
    require_scm,
    tool_ctx,
)

from mergecraft.mcp.check_runs import list_check_runs_tool
from mergecraft.mcp.checkout import last_reviewed_sha
from mergecraft.mcp.comment import create_issue_comment_tool
from mergecraft.mcp.commit_info import get_commit_info_tool
from mergecraft.mcp.issue_comments import get_issue_comments_tool
from mergecraft.mcp.pr_info import get_pull_request_tool
from mergecraft.mcp.review_comments import list_pull_request_reviews_tool

# Operations the GitHub client + MCP tools exercise today. DG9.2's protocol must
# express every one without leaking GitHub-shaped types into core call sites.
_GITHUB_REST_OPERATIONS: frozenset[str] = frozenset(
    {
        "get_repo",
        "get_commit",
        "get_issue",
        "create_issue",
        "update_issue",
        "list_issue_comments",
        "get_issue_comment",
        "create_issue_comment",
        "update_issue_comment",
        "list_issues",
        "create_label",
        "add_labels",
        "get_pull",
        "update_pull",
        "list_pull_files",
        "list_reviews",
        "get_review",
        "create_review",
        "submit_review",
        "delete_pending_review",
        "get_review_comment",
        "create_review_comment_reply",
        "create_status",
        "list_check_suites_for_ref",
        "get_check_suite",
        "list_check_runs_for_ref",
        "list_workflow_run_artifacts",
        "download_artifact_zip",
        "graphql",
    }
)

_GITHUB_MCP_READ_TOOLS: frozenset[str] = frozenset(
    {
        "get_pull_request",
        "get_issue",
        "get_issue_comments",
        "get_issue_events",
        "get_commit_info",
        "list_pull_request_reviews",
        "get_review_comments",
        "list_check_runs",
        "get_check_suite",
        "get_check_suite_logs",
    }
)

_GITHUB_MCP_WRITE_TOOLS: frozenset[str] = frozenset(
    {
        "create_issue_comment",
        "edit_issue_comment",
        "reply_to_review_comment",
        "create_pull_request_review",
        "create_issue",
        "close_issue",
        "reopen_issue",
        "create_pull_request",
        "update_pull_request_body",
        "close_pull_request",
        "add_labels",
        "remove_labels",
        "resolve_review_thread",
        "checkout_pr",
    }
)

# Behavioural snapshot captured on ``origin/pre-0.0.1`` before any extraction.
_SNAPSHOT_CALLS: tuple[tuple[str, str], ...] = (
    ("GET", "/repos/acme/demo/pulls/7"),
    ("POST", "/graphql"),
    ("GET", "/repos/acme/demo/issues/42/comments"),
    ("GET", "/repos/acme/demo/pulls/7/reviews"),
    ("POST", "/repos/acme/demo/issues/42/comments"),
    ("GET", "/repos/acme/demo/commits/abc123def456"),
    ("GET", "/repos/acme/demo/commits/main/check-suites"),
)

_SNAPSHOT_TOOL_OUTPUTS: dict[str, dict[str, Any]] = {
    "get_pull_request": {
        "number": 7,
        "title": "Add widgets",
        "state": "open",
        "base": "main",
        "head": "feature/widgets",
        "isFork": False,
        "author": "dev1",
        "labels": ["enhancement"],
        "closingIssues": [{"number": 42, "title": "Track widgets"}],
    },
    "get_issue_comments": {
        "issue_number": 42,
        "count": 1,
        "comments": [{"id": 9001, "body": "Looks good", "user": "reviewer"}],
    },
    "list_pull_request_reviews": {
        "pull_number": 7,
        "count": 1,
    },
    "get_commit_info": {
        "sha": "abc123def456",
        "message": "Add widgets",
        "author": "dev1",
    },
}


@_DG9_2_XFAIL
def test_every_github_operation_is_expressible_through_the_protocol() -> None:
    """Every GitHub REST helper and MCP tool maps to a protocol operation."""
    require_scm()
    from mergecraft.scm.protocol import (
        protocol_operation_names,
        protocol_supports_github_operations,
    )

    declared = protocol_operation_names()
    assert declared, "ScmProvider must declare at least one operation"

    missing_rest = _GITHUB_REST_OPERATIONS - declared
    assert not missing_rest, f"protocol missing GitHub REST operations: {sorted(missing_rest)}"

    missing_mcp = (_GITHUB_MCP_READ_TOOLS | _GITHUB_MCP_WRITE_TOOLS) - declared
    assert not missing_mcp, f"protocol missing MCP-level operations: {sorted(missing_mcp)}"

    assert protocol_supports_github_operations() is True


@pytest.mark.asyncio
async def test_github_adapter_behaviour_is_unchanged(tmp_path: Path) -> None:
    """Broad behavioural snapshot over GitHub MCP tools — the compatibility pin."""
    transport = github_snapshot_transport()
    github = RecordingGitHubClient(transport=transport)
    ctx = tool_ctx(tmp_path, github=github)

    pr_result = await get_pull_request_tool(ctx).execute({"pull_number": 7})
    assert pr_result.is_error is False
    pr_payload = json.loads(pr_result.content[0]["text"])
    for key, value in _SNAPSHOT_TOOL_OUTPUTS["get_pull_request"].items():
        assert pr_payload.get(key) == value, f"get_pull_request.{key}"

    comments_result = await get_issue_comments_tool(ctx).execute({"issue_number": 42})
    assert comments_result.is_error is False
    comments_payload = json.loads(comments_result.content[0]["text"])
    assert comments_payload["count"] == _SNAPSHOT_TOOL_OUTPUTS["get_issue_comments"]["count"]
    assert comments_payload["comments"] == _SNAPSHOT_TOOL_OUTPUTS["get_issue_comments"]["comments"]

    reviews_result = await list_pull_request_reviews_tool(ctx).execute({"pull_number": 7})
    assert reviews_result.is_error is False
    reviews_payload = json.loads(reviews_result.content[0]["text"])
    assert reviews_payload["count"] == _SNAPSHOT_TOOL_OUTPUTS["list_pull_request_reviews"]["count"]

    comment_result = await create_issue_comment_tool(ctx).execute(
        {"issueNumber": 42, "body": "Progress update"}
    )
    assert comment_result.is_error is False

    commit_result = await get_commit_info_tool(ctx).execute({"sha": "abc123def456"})
    assert commit_result.is_error is False
    commit_payload = json.loads(commit_result.content[0]["text"])
    assert commit_payload["sha"] == _SNAPSHOT_TOOL_OUTPUTS["get_commit_info"]["sha"]
    assert commit_payload["message"] == _SNAPSHOT_TOOL_OUTPUTS["get_commit_info"]["message"]

    checks_result = await list_check_runs_tool(ctx).execute({"ref": "main"})
    assert checks_result.is_error is False

    recorded = tuple((method, path) for method, path, _payload in github.calls)
    assert recorded == _SNAPSHOT_CALLS, (
        "GitHub adapter behavioural snapshot drifted — update only after deliberate "
        f"behaviour change; got {recorded!r}"
    )


@_DG9_2_XFAIL
def test_no_github_specific_type_leaks_into_core() -> None:
    """Core runtime surfaces depend on ``ScmProvider``, not ``GitHubClient``."""
    require_scm()
    from mergecraft.scm.protocol import ScmProvider

    context_mod = importlib.import_module("mergecraft.mcp.context")
    tool_context = context_mod.ToolContext
    field_names = {field.name for field in dataclasses.fields(tool_context)}
    assert "scm" in field_names, "ToolContext must expose scm: ScmProvider"
    assert "github" not in field_names, "ToolContext must not retain a github: GitHubClient field"

    scm_field = next(field for field in dataclasses.fields(tool_context) if field.name == "scm")
    annotation = scm_field.type
    if isinstance(annotation, str):
        assert "ScmProvider" in annotation
    else:
        assert annotation is ScmProvider or getattr(annotation, "__name__", "") == "ScmProvider"

    leaking_modules: list[str] = []
    for module_name in (
        "mergecraft.mcp.pr_info",
        "mergecraft.mcp.checkout",
        "mergecraft.mcp.review",
        "mergecraft.mcp.comment",
        "mergecraft.mcp.issue_comments",
        "mergecraft.main",
    ):
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        if "GitHubClient" in source or "ctx.github" in source:
            leaking_modules.append(module_name)

    assert not leaking_modules, (
        "GitHub-specific types or ctx.github call sites leaked into core modules: "
        f"{leaking_modules}"
    )


@_DG9_2_XFAIL
@pytest.mark.asyncio
async def test_review_publication_goes_through_the_protocol(tmp_path: Path) -> None:
    """Validated terminal submissions publish via the SCM provider, not ctx.github."""
    require_scm()
    from mergecraft.scm.protocol import RecordingScmProvider, resolve_scm_provider

    from mergecraft.mcp.review import publish_pull_request_review
    from mergecraft.mcp.tool_state import TerminalSubmission, primary_repo_state

    recording = RecordingScmProvider()
    ctx = tool_ctx(tmp_path)
    ctx.tool_state.terminal_submission = TerminalSubmission(
        id="sub-1",
        verdict="approve",
        summary="No blocking issues.",
        findings=[],
        payload_hash="abc",
        submitted_at="2026-08-18T00:00:00Z",
        attempt_id=1,
    )
    primary_repo_state(ctx.tool_state).issue_number = 7

    object.__setattr__(ctx, "scm", recording)
    if hasattr(ctx, "github"):
        pytest.fail("ToolContext still exposes github alongside scm")

    outcome = await publish_pull_request_review(ctx)
    assert outcome is not None
    assert recording.publications, "publish_pull_request_review must delegate to ScmProvider"
    assert recording.publications[0]["pull_number"] == 7
    assert resolve_scm_provider(ctx) is recording


@_DG9_2_XFAIL
def test_checkout_and_diff_semantics_are_preserved() -> None:
    """Checkout + incremental diff semantics survive the protocol extraction."""
    require_scm()
    from mergecraft.scm.checkout import checkout_pull_request
    from mergecraft.scm.protocol import InMemoryScmProvider

    provider = InMemoryScmProvider(
        reviews=[
            {
                "body": "*via mergecraft*\nPrior review",
                "commit_id": "deadbeef00000000000000000000000000000000",
            }
        ],
        pull={
            "number": 7,
            "head": {"ref": "feature", "sha": "abc123def4567890123456789012345678901234"},
            "base": {"ref": "main"},
        },
        diff_text="diff --git a/src/a.py b/src/a.py\n+change\n",
    )

    prior = last_reviewed_sha(
        provider.reviews_payload(),
        head_sha="abc123def4567890123456789012345678901234",
    )
    assert prior == "deadbeef00000000000000000000000000000000"

    result = checkout_pull_request(
        provider,
        owner="acme",
        repo="demo",
        pull_number=7,
        cwd="/tmp/demo",
        temp_dir="/tmp/demo",
        last_reviewed_sha=prior,
    )
    assert result["diffPath"].endswith("pr-7.diff")
    assert "incrementalDiffPath" in result
    assert result["lastReviewedSha"] == prior
    assert result["incrementalChangedPaths"] == ["src/a.py"]
