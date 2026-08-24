"""DG9.1 RED suite — ``ScmProvider`` protocol contract (D10).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (DG9.1 RED,
DG9.2 impl). Six tests are ``@pytest.mark.xfail(strict=False)`` pending protocol
extraction; ``test_github_tool_endpoint_behaviour_is_unchanged`` carries the
pre-refactor behavioural pins that must keep passing through DG9.2.

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
        "download_workflow_run_logs",
        "graphql",
    }
)

_GITHUB_MCP_READ_TOOLS: frozenset[str] = frozenset(
    {
        "get_pull_request",
        "get_issue",
        "get_issue_comments",
        "get_commit_info",
        "list_pull_request_reviews",
        "list_check_runs",
        "get_check_suite",
    }
)

# MCP tools whose implementations call generic REST/GraphQL ops — not namesake
# protocol methods (declare, don't fake).
_MCP_TOOL_REQUIRED_OPS: dict[str, frozenset[str]] = {
    "get_issue_events": frozenset({"get"}),
    "get_check_suite_logs": frozenset({"get", "download_workflow_run_logs"}),
    "get_review_comments": frozenset({"graphql"}),
    "checkout_pr": frozenset({"get_pull", "list_reviews", "get"}),
}

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
    }
)

_CORE_SCM_MODULES: tuple[str, ...] = (
    "mergecraft.mcp.pr_info",
    "mergecraft.mcp.checkout",
    "mergecraft.mcp.review",
    "mergecraft.mcp.comment",
    "mergecraft.mcp.issue_comments",
    "mergecraft.mcp.issue_events",
    "mergecraft.mcp.review_comments",
    "mergecraft.mcp.check_runs",
    "mergecraft.mcp.check_suite",
    "mergecraft.ci.providers.github_actions",
    "mergecraft.ci.intelligence",
    "mergecraft.utils.status_checks",
    "mergecraft.utils.code_scanning",
)

# Per-endpoint behavioural pins captured on ``origin/pre-0.0.1`` before any
# extraction. One case per MCP tool: the endpoints it reaches, and the fields of
# its rendered payload that the adapter must keep producing. Kept per tool so a
# deliberate change to one endpoint invalidates only its own case.
_ENDPOINT_CASES: tuple[Any, ...] = (
    pytest.param(
        get_pull_request_tool,
        {"pull_number": 7},
        (("GET", "/repos/acme/demo/pulls/7"), ("POST", "/graphql")),
        {
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
        id="get_pull_request",
    ),
    pytest.param(
        get_issue_comments_tool,
        {"issue_number": 42},
        (("GET", "/repos/acme/demo/issues/42/comments"),),
        {
            "issue_number": 42,
            "count": 1,
            "comments": [{"id": 9001, "body": "Looks good", "user": "reviewer"}],
        },
        id="get_issue_comments",
    ),
    pytest.param(
        list_pull_request_reviews_tool,
        {"pull_number": 7},
        (("GET", "/repos/acme/demo/pulls/7/reviews"),),
        {"pull_number": 7, "count": 1},
        id="list_pull_request_reviews",
    ),
    pytest.param(
        create_issue_comment_tool,
        {"issueNumber": 42, "body": "Progress update"},
        (("POST", "/repos/acme/demo/issues/42/comments"),),
        {},
        id="create_issue_comment",
    ),
    pytest.param(
        get_commit_info_tool,
        {"sha": "abc123def456"},
        (("GET", "/repos/acme/demo/commits/abc123def456"),),
        {"sha": "abc123def456", "message": "Add widgets", "author": "dev1"},
        id="get_commit_info",
    ),
    pytest.param(
        list_check_runs_tool,
        {"ref": "main"},
        # Inverted for #266 (D13): ``list_check_runs`` must reach check-runs, not
        # check-suites.
        (("GET", "/repos/acme/demo/commits/main/check-runs"),),
        {},
        id="list_check_runs",
    ),
)


def test_github_adapter_satisfies_the_protocol() -> None:
    """GitHubScmAdapter fully implements ``ScmProvider`` (not just name coverage)."""
    require_scm()
    from mergecraft.scm.github import create_github_scm
    from mergecraft.scm.protocol import validate_provider

    adapter = create_github_scm("test-token")
    report = validate_provider(adapter)
    assert report.complete is True, report.missing


def test_every_github_operation_is_expressible_through_the_protocol() -> None:
    """Every GitHub REST helper and MCP tool maps to a protocol operation."""
    require_scm()
    from mergecraft.scm.protocol import (
        mcp_generic_tool_names,
        protocol_operation_names,
        protocol_supports_github_operations,
    )

    declared = protocol_operation_names()
    assert declared, "ScmProvider must declare at least one operation"

    missing_rest = _GITHUB_REST_OPERATIONS - declared
    assert not missing_rest, f"protocol missing GitHub REST operations: {sorted(missing_rest)}"

    missing_mcp = (_GITHUB_MCP_READ_TOOLS | _GITHUB_MCP_WRITE_TOOLS) - declared
    assert not missing_mcp, f"protocol missing MCP-level operations: {sorted(missing_mcp)}"

    generic_tools = mcp_generic_tool_names()
    assert generic_tools == frozenset(_MCP_TOOL_REQUIRED_OPS)
    for tool_name, required_ops in _MCP_TOOL_REQUIRED_OPS.items():
        missing_ops = required_ops - declared
        assert not missing_ops, (
            f"MCP tool {tool_name!r} requires protocol ops {sorted(missing_ops)}"
        )

    assert protocol_supports_github_operations() is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool_factory", "params", "expected_calls", "expected_payload"), _ENDPOINT_CASES
)
async def test_github_tool_endpoint_behaviour_is_unchanged(
    tmp_path: Path,
    tool_factory: Any,
    params: dict[str, Any],
    expected_calls: tuple[tuple[str, str], ...],
    expected_payload: dict[str, Any],
) -> None:
    """Per-endpoint compatibility pin over the GitHub MCP tools.

    Each tool is exercised against its own recording client, so a deliberate
    change to one endpoint or one rendered payload fails only that case instead
    of invalidating the behaviour pin for every other tool.
    """
    transport = github_snapshot_transport()
    github = RecordingGitHubClient(transport=transport)
    ctx = tool_ctx(tmp_path, github=github)

    result = await tool_factory(ctx).execute(params)

    assert result.is_error is False
    recorded = tuple((method, path) for method, path, _payload in github.calls)
    assert recorded == expected_calls
    if expected_payload:
        payload = json.loads(result.content[0]["text"])
        for key, value in expected_payload.items():
            assert payload.get(key) == value, key


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

    github_shim_modules: list[str] = []
    for module_name in _CORE_SCM_MODULES:
        module = importlib.import_module(module_name)
        source = inspect.getsource(module)
        if "ctx.github" in source:
            github_shim_modules.append(module_name)

    assert not github_shim_modules, (
        "Core modules must call ctx.scm, not the ctx.github compatibility shim: "
        f"{github_shim_modules}"
    )


def test_check_suite_workflow_listing_is_github_client_not_scm_protocol() -> None:
    """GitHub Actions CI listing stays on GitHubClient; GitLab must not stub it."""
    require_scm()
    from mergecraft.scm.protocol import protocol_operation_names

    assert "list_workflow_runs_for_check_suite" not in protocol_operation_names()
    from mergecraft.scm.github import GitHubScmAdapter

    assert not hasattr(GitHubScmAdapter, "list_workflow_runs_for_check_suite")
    root = Path(__file__).resolve().parents[2]
    github_src = (root / "src/mergecraft/scm/github.py").read_text(encoding="utf-8")
    assert "list_workflow_runs_for_check_suite" not in github_src
    for rel in (
        "src/mergecraft/ci/intelligence.py",
        "src/mergecraft/ci/providers/github_actions.py",
    ):
        text = (root / rel).read_text(encoding="utf-8")
        assert "github_client_from_scm" in text
        assert "list_workflow_runs_for_check_suite" in text


@pytest.mark.asyncio
async def test_review_publication_goes_through_the_protocol(tmp_path: Path) -> None:
    """Validated terminal submissions publish via the SCM provider, not ctx.github."""
    require_scm()
    from tests.scm.support import RecordingScmProvider

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
    assert ctx.scm is recording


@pytest.mark.asyncio
async def test_protocol_list_check_runs_alias_reaches_the_check_runs_endpoint(
    tmp_path: Path,
) -> None:
    """#266 second ingress — the protocol alias must hit check-runs, not check-suites.

    ``GitHubScmAdapter.list_check_runs`` used to forward to ``list_check_suites_for_ref``.
    Nothing calls it today, but it is the protocol's ``list_check_runs`` operation, so it
    carried the same defect as the MCP tool and is pinned separately from it.
    """
    require_scm()
    from mergecraft.scm.github import GitHubScmAdapter

    _ = tmp_path
    github = RecordingGitHubClient(transport=github_snapshot_transport())
    adapter = GitHubScmAdapter(github)

    payload = await adapter.list_check_runs("acme", "demo", "main")

    assert [path for _method, path, _payload in github.calls] == [
        "/repos/acme/demo/commits/main/check-runs"
    ]
    assert "check_runs" in payload


def test_checkout_and_diff_semantics_are_preserved() -> None:
    """Checkout + incremental diff semantics survive the protocol extraction."""
    require_scm()
    from tests.scm.support import InMemoryScmProvider, checkout_pull_request

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
