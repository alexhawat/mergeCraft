"""Review-only mutation refusal across every shell and push policy combination."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from mergecraft.mcp.server import build_orchestrator_tools, create_mcp_app
from tests.security.conftest import PUSH_MODES, SHELL_MODES
from tests.support.tool_context import github_client_from_ctx

CELL_IDS = [f"shell-{s}__push-{p}" for s in SHELL_MODES for p in PUSH_MODES]
CELLS = [(s, p) for s in SHELL_MODES for p in PUSH_MODES]


@pytest.mark.parametrize(("shell", "push"), CELLS, ids=CELL_IDS)
def test_tool_registration_deltas(make_tool_ctx, shell: str, push: str) -> None:
    ctx = make_tool_ctx(shell=shell, push=push)
    names = {t.name for t in build_orchestrator_tools(ctx)}
    assert ("shell" in names) == (shell == "restricted")
    assert ("kill_background" in names) == (shell == "restricted")
    assert not {"push_branch", "push_tags", "delete_branch", "commit_changes"}.intersection(names)


@pytest.mark.parametrize(("shell", "push"), CELLS, ids=CELL_IDS)
async def test_direct_git_push_subcommand_always_blocked(
    make_tool_ctx, shell: str, push: str
) -> None:
    """W4.2 — the generic ``git`` tool never runs push/fetch/clone, any cell."""
    ctx = make_tool_ctx(shell=shell, push=push)
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    git = tools["git"]
    for subcommand in ("push", "fetch", "pull", "clone"):
        result = await git.execute({"command": subcommand, "args": []})
        assert result.is_error, f"git {subcommand} executed under shell={shell} push={push}"
        assert "not available" in result.content[0]["text"]


@pytest.mark.parametrize(("shell", "push"), CELLS, ids=CELL_IDS)
def test_removed_mutations_cannot_touch_git_or_scm(
    make_tool_ctx, monkeypatch: pytest.MonkeyPatch, shell: str, push: str
) -> None:
    ctx = make_tool_ctx(shell=shell, push=push)
    git_calls: list[object] = []
    monkeypatch.setattr("mergecraft.mcp.git._run_git", lambda *a, **kw: git_calls.append(a))
    app = create_mcp_app(build_orchestrator_tools(ctx), ctx, auth_token="test-token")
    attempts = (
        [("push_branch", {"branchName": branch}) for branch in ("feature", "main", "heads/main")]
        + [
            ("delete_branch", {"branchName": branch, "remote": remote})
            for branch in ("feature", "main", "heads/main")
            for remote in (False, True)
        ]
        + [
            ("push_tags", {"tags": ["v9.9.9"]}),
            ("commit_changes", {"message": "must not commit"}),
            ("create_pull_request", {"title": "must not open", "body": "probe", "base": "main"}),
            ("update_pull_request_body", {"pull_number": 1, "body": "probe"}),
            ("close_pull_request", {"pull_number": 1}),
        ]
    )
    with TestClient(app, headers={"Authorization": "Bearer test-token"}) as client:
        for name, arguments in attempts:
            result = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                },
            ).json()
            assert result["error"]["code"] == -32601
    assert git_calls == []
    assert github_client_from_ctx(ctx).calls == []
