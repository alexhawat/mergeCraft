"""Plan W4 - adversarial ``shell x push`` matrix proving the W1-W3 invariants.

Every ``shell in {disabled, restricted, enabled} x push in {disabled,
restricted, enabled}`` cell gets adversarial coverage per invariant class:

- W4.1 tool-registration deltas (``shell``/``kill_background`` only under
  ``shell=restricted``; push tools registered but policy-enforced per call);
- W4.2 push-policy fail-closed - direct ``git push``, ``push_branch`` /
  ``push_tags`` / ``delete_branch --remote`` MCP calls, and the
  ``commit_changes`` GitHub-API ref mutation (gh-equivalent);
- cells whose contract already holds are plain tests (W2 push-policy plumbing
  for ``delete_branch --remote`` / ``commit_changes`` reconciled 2026-08-11).
"""

from __future__ import annotations

from typing import Any

import pytest

import mergecraft.mcp.git as git_mod
from mergecraft.mcp.server import build_orchestrator_tools
from tests.security.conftest import PUSH_MODES, SHELL_MODES
from tests.support.run_main_harness import FakeGitHubClient
from tests.support.tool_context import github_client_from_ctx, write_capable_mcp_mode

CELL_IDS = [f"shell-{s}__push-{p}" for s in SHELL_MODES for p in PUSH_MODES]
CELLS = [(s, p) for s in SHELL_MODES for p in PUSH_MODES]


@pytest.mark.parametrize(("shell", "push"), CELLS, ids=CELL_IDS)
def test_tool_registration_deltas(make_tool_ctx, shell: str, push: str) -> None:
    """W4.1 — the shell tool exists iff ``shell=restricted``; push tools are
    always registered and must enforce policy per invocation (not by omission).
    """
    ctx = make_tool_ctx(shell=shell, push=push)
    names = {t.name for t in build_orchestrator_tools(ctx)}
    if shell == "restricted":
        assert "shell" in names, "restricted shell must expose the shell tool"
        assert "kill_background" in names
    else:
        assert "shell" not in names, f"shell tool registered under shell={shell}"
        assert "kill_background" not in names
    for push_tool in ("push_branch", "push_tags", "delete_branch"):
        assert push_tool in names, (
            f"{push_tool} missing under push={push}: policy must be enforced per call"
        )


class _RecordingGit:
    """Monkeypatch target for ``_run_git``: records argv, never touches a remote."""

    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.status_output = ""
        self.current_branch = "feature-branch"

    def __call__(self, args: list[str], **_kwargs: Any) -> str:
        self.calls.append(list(args))
        if args[:2] == ["rev-parse", "--abbrev-ref"]:
            return f"{self.current_branch}\n"
        if args[:1] == ["rev-parse"]:
            return "0" * 40 + "\n"
        if args[:1] == ["status"]:
            return self.status_output
        return ""

    def push_attempts(self) -> list[list[str]]:
        return [c for c in self.calls if c and c[0] == "push"]


@pytest.fixture
def recording_git(monkeypatch: pytest.MonkeyPatch) -> _RecordingGit:
    recorder = _RecordingGit()
    monkeypatch.setattr(git_mod, "_run_git", recorder)
    return recorder


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
async def test_push_branch_fail_closed_when_push_disabled(
    make_tool_ctx, recording_git: _RecordingGit, shell: str, push: str
) -> None:
    """W4.2 — ``push=disabled`` refuses the push *before* any git invocation."""
    ctx = make_tool_ctx(shell=shell, push=push)
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        result = await tools["push_branch"].execute({"branchName": "feature-x"})
    if push == "disabled":
        assert result.is_error, f"push_branch succeeded under push=disabled ({CELL_IDS})"
        assert "disabled" in result.content[0]["text"]
        assert not recording_git.push_attempts(), "push argv reached git despite policy"
    else:
        assert not result.is_error, (
            f"push_branch of a feature branch should pass under push={push}: {result.content}"
        )


@pytest.mark.parametrize("shell", SHELL_MODES)
async def test_push_branch_to_default_branch_blocked_when_restricted(
    make_tool_ctx, recording_git: _RecordingGit, shell: str
) -> None:
    """W4.2 — ``push=restricted`` protects the default branch."""
    ctx = make_tool_ctx(shell=shell, push="restricted")
    from mergecraft.mcp.tool_state import primary_repo_state

    primary_repo_state(ctx.tool_state).default_branch = "main"
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        result = await tools["push_branch"].execute({"branchName": "main"})
    assert result.is_error, "push to default branch allowed under push=restricted"
    assert "default branch" in result.content[0]["text"]
    assert not recording_git.push_attempts()


@pytest.mark.parametrize("shell", SHELL_MODES)
async def test_push_tags_fail_closed_when_push_disabled(
    make_tool_ctx, recording_git: _RecordingGit, shell: str
) -> None:
    """W4.2 — tag pushes are pushes."""
    ctx = make_tool_ctx(shell=shell, push="disabled")
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        result = await tools["push_tags"].execute({"tags": ["v9.9.9"]})
    assert result.is_error, "push_tags succeeded under push=disabled"
    assert not recording_git.push_attempts()


@pytest.mark.parametrize("shell", SHELL_MODES)
async def test_delete_remote_branch_fail_closed_when_push_disabled(
    make_tool_ctx, recording_git: _RecordingGit, shell: str
) -> None:
    """W4.2 — remote branch deletion is a push and must fail closed.

    Fails if the guard is deleted: with ``_run_git`` succeeding, an unguarded
    tool returns success and the push attempt is recorded.
    """
    ctx = make_tool_ctx(shell=shell, push="disabled")
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        result = await tools["delete_branch"].execute({"branchName": "feature-x", "remote": True})
    assert result.is_error, "remote delete_branch executed a push under push=disabled"
    assert not recording_git.push_attempts(), "delete push argv reached git despite policy"


@pytest.mark.parametrize("shell", SHELL_MODES)
async def test_delete_remote_default_branch_blocked_when_restricted(
    make_tool_ctx, recording_git: _RecordingGit, shell: str
) -> None:
    """W4.2 — ``push=restricted`` must also protect the default branch from deletion."""
    from mergecraft.mcp.tool_state import primary_repo_state

    ctx = make_tool_ctx(shell=shell, push="restricted")
    primary_repo_state(ctx.tool_state).default_branch = "main"
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        result = await tools["delete_branch"].execute({"branchName": "main", "remote": True})
    assert result.is_error, "remote delete of default branch allowed under push=restricted"
    assert not recording_git.push_attempts()


@pytest.mark.parametrize("shell", SHELL_MODES)
async def test_commit_changes_does_not_mutate_remote_ref_when_push_disabled(
    make_tool_ctx, recording_git: _RecordingGit, shell: str, planted_repo
) -> None:
    """W4.2 — the gh-equivalent API mutation (PATCH git/refs) is a push.

    ``commit_changes`` pushes the committed SHA to the remote ref through the
    GitHub API; under ``push=disabled`` that mutation must not be attempted
    (a local-only commit remains acceptable — the push is what is gated).
    """
    recording_git.status_output = " M change.txt\n"
    ctx = make_tool_ctx(shell=shell, push="disabled", signed_commits=True)
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    commit = tools["commit_changes"]
    with write_capable_mcp_mode():
        await commit.execute({"message": "attempt remote mutation"})
    github: FakeGitHubClient = github_client_from_ctx(ctx)  # type: ignore[assignment]
    ref_mutations = [c for c in github.calls if c[0] == "patch" and "git/refs" in str(c[1])]
    assert not ref_mutations, f"API ref mutation attempted under push=disabled: {ref_mutations}"


@pytest.mark.parametrize("shell", SHELL_MODES)
async def test_commit_changes_does_not_mutate_default_branch_when_restricted(
    make_tool_ctx, recording_git: _RecordingGit, shell: str
) -> None:
    """W4.2 — the API ref mutation must honor restricted-mode branch protection."""
    from mergecraft.mcp.tool_state import primary_repo_state

    recording_git.status_output = " M change.txt\n"
    recording_git.current_branch = "main"

    ctx = make_tool_ctx(shell=shell, push="restricted", signed_commits=True)
    primary_repo_state(ctx.tool_state).default_branch = "main"
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        await tools["commit_changes"].execute({"message": "attempt default-branch mutation"})
    github: FakeGitHubClient = github_client_from_ctx(ctx)  # type: ignore[assignment]
    ref_mutations = [c for c in github.calls if c[0] == "patch" and "git/refs" in str(c[1])]
    assert not ref_mutations, (
        f"API ref mutation on default branch attempted under push=restricted: {ref_mutations}"
    )


async def test_local_delete_branch_still_allowed_when_push_disabled(
    make_tool_ctx, recording_git: _RecordingGit
) -> None:
    """W4.2 edge — local branch deletion is not a push and stays available."""
    ctx = make_tool_ctx(shell="restricted", push="disabled")
    tools = {t.name: t for t in build_orchestrator_tools(ctx)}
    with write_capable_mcp_mode():
        result = await tools["delete_branch"].execute({"branchName": "old", "remote": False})
    assert not result.is_error, result.content
    assert recording_git.calls[-1][:2] == ["branch", "-D"]
