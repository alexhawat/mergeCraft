"""#282 / D9: primary reviewer may publish; subagents still cannot.

``create_pull_request_review`` is ``ToolClass.REVIEW_WRITE`` + ``mutates=True``
and is not in ``REVIEWER_ALLOWED_TOOL_CLASSES``, so ``/mcp/reviewer`` currently
omits it. Expanding that frozenset without a split would also drop the name
off ``subagent_denied_tool_names``. D9 admits publication on the **primary**
reviewer only: ``REVIEW_WRITE`` + a primary-only mutating allowlist that
includes ``create_pull_request_review``. Subagents stay denied.

``git`` stays on ``/mcp/reviewer`` — it is still ``REPOSITORY_READ`` after
morning A / #291. Do not take it off this surface here (D6).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.testclient import TestClient

from mergecraft.agents.gates import subagent_denied_tool_names
from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.server import (
    MCP_REVIEWER_ENDPOINT,
    build_orchestrator_tools,
    build_reviewer_tools,
    create_mcp_app,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path

_REVIEWER_EXCLUDED = frozenset(
    {
        "push_branch",
        "upload_file",
        "delete_branch",
        "create_pull_request",
        "close_pull_request",
        "commit_changes",
    }
)


def _tool_ctx(tmp_path: Path) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="unknown"),
            shell="restricted",
            push="restricted",
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        signed_commits=True,
        xrepo=XrepoConfig(mode="explicit", read=["other"], write=["other"]),
        static_checks_enabled=True,
    )


def _reviewer_client(tmp_path: Path) -> TestClient:
    ctx = _tool_ctx(tmp_path)
    return TestClient(
        create_mcp_app(
            build_orchestrator_tools(ctx),
            ctx,
            role_tools={"reviewer": build_reviewer_tools(ctx)},
        )
    )


def _listed_names(client: TestClient) -> set[str]:
    response = client.post(
        MCP_REVIEWER_ENDPOINT,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    return {entry["name"] for entry in body["result"]["tools"]}


def test_reviewer_tools_list_includes_create_pull_request_review(tmp_path: Path) -> None:
    """W11.2 / W13 / C6: ``/mcp/reviewer`` ``tools/list`` admits primary publication and C6 tools.

    Session tools ``set_output``, ``select_mode``, ``report_progress`` are admitted
    on the primary reviewer via ``PRIMARY_MUTATING_ALLOWLIST``. C6 tools
    ``submit_review_verdict`` (TERMINAL_PROTOCOL), ``verify_agent_findings``
    (VERIFICATION), and ``record_finding_verdict`` (REVIEW_WRITE + mutates, in
    ``PRIMARY_MUTATING_ALLOWLIST``) are also admitted on the primary reviewer only.
    """
    names = _listed_names(_reviewer_client(tmp_path))
    assert "create_pull_request_review" in names
    assert "checkout_pr" in names
    for session_tool in ("set_output", "select_mode", "report_progress"):
        assert session_tool in names, f"{session_tool!r} must be on primary /mcp/reviewer"
    for c6_tool in ("submit_review_verdict", "verify_agent_findings", "record_finding_verdict"):
        assert c6_tool in names, f"{c6_tool!r} must be on primary /mcp/reviewer (C6)"
    for dispatch_tool in ("record_reviewer_dispatch_run", "record_reviewer_dispatch_error"):
        assert dispatch_tool in names, f"{dispatch_tool!r} must be on primary /mcp/reviewer (D7)"


def test_reviewer_tools_list_keeps_git_and_excludes_repo_mutations(tmp_path: Path) -> None:
    """W11.2 control: ``git`` stays; repo/GitHub mutations stay off (D6 / D9)."""
    names = _listed_names(_reviewer_client(tmp_path))
    assert "git" in names
    assert "checkout_pr" in names
    missing = _REVIEWER_EXCLUDED & names
    assert not missing, f"reviewer leaked mutation tools: {sorted(missing)}"


def test_reviewer_tools_call_push_branch_errors(tmp_path: Path) -> None:
    """W11.2: ``tools/call`` ``push_branch`` on ``/mcp/reviewer`` is unknown / unauthorized."""
    client = _reviewer_client(tmp_path)
    response = client.post(
        MCP_REVIEWER_ENDPOINT,
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "push_branch", "arguments": {}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert "error" in body
    assert body["error"]["code"] == -32601
    assert "push_branch" in body["error"]["message"]


def test_subagent_deny_list_still_contains_create_pull_request_review(tmp_path: Path) -> None:
    """W11.5 / D9 pin: subagents stay denied review publication after the primary allow.

    Holds today (class complement). Must keep holding after W13 expands the
    primary reviewer allowlist — do not xfail this; a silent drop is a product
    break.
    """
    ctx = _tool_ctx(tmp_path)
    denied = subagent_denied_tool_names(ctx)
    assert "create_pull_request_review" in denied
    assert "push_branch" in denied
    assert "checkout_pr" not in denied
    _assert_real_orchestrator_has_publication(ctx)


def _assert_real_orchestrator_has_publication(ctx: ToolContext) -> None:
    names = {spec.name for spec in build_orchestrator_tools(ctx)}
    assert "create_pull_request_review" in names
