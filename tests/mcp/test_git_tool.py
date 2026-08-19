"""Tests for git MCP tool input normalization (redundant subcommand tolerance).

Also covers the reviewer-surface hardening contract for issue #257 (D7) and the
``commit_changes`` honesty contract for issue #259 (D9).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.git import commit_changes_tool, git_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

# A path that is deliberately outside any test repo root.
OUTSIDE_DIR = "/some/repo/dir"

Shell = Literal["disabled", "restricted", "enabled"]


def _resolved(path: Path) -> str:
    return str(path.resolve())


def _ctx(
    tmp_path: Path,
    *,
    shell: Shell = "restricted",
    push: Literal["disabled", "restricted", "enabled"] = "restricted",
    github: GitHubClient | None = None,
) -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request"), shell=shell, push=push),
        github=github or GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


class _RunGitRecorder:
    """Captures the argv passed to _run_git and returns canned output."""

    def __init__(self, output: str = "ok") -> None:
        self.calls: list[list[str]] = []
        self.output = output

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        self.calls.append([str(a) for a in args])
        return self.output


async def test_git_prefix_is_stripped_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder("clean tree")
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "git status"})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert "clean tree" in payload["output"]
    assert recorder.calls == [["status"]]


async def test_duplicate_subcommand_arg_is_dropped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "status", "args": ["status", "--porcelain"]}
    )
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["status", "--porcelain"]]


async def test_redundant_git_prefix_and_subcommand_together(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "git status", "args": ["status", "-s"]}
    )
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["status", "-s"]]


async def test_invalid_subcommand_after_normalization_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "rm -rf"})
    assert result.is_error is True
    assert "invalid git subcommand" in result.content[0]["text"]
    assert recorder.calls == []


async def test_global_c_option_inside_repo_root_is_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    inside = _resolved(tmp_path)
    result = await git_tool(_ctx(tmp_path)).execute({"command": "status", "args": ["-C", inside]})
    assert result.is_error is False, result.content[0]["text"]
    # `-C` pointing at the primary repo root must still be forwarded before the
    # subcommand, not rejected as a subcommand and not swallowed.
    assert recorder.calls == [["-C", inside, "status"]]


@pytest.mark.xfail(reason="green after W2: -C confined to the primary repo root", strict=False)
async def test_global_c_option_outside_repo_root_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#257 / D7: `-C` must not point the tool at a directory outside the repo."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "status", "args": ["-C", OUTSIDE_DIR]}
    )
    assert result.is_error is True
    assert OUTSIDE_DIR in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after W2: -c is never forwarded", strict=False)
@pytest.mark.parametrize("flag_args", [["-c", "core.quotepath=false", "-s"], ["--config-env=x=Y"]])
async def test_c_config_option_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag_args: list[str]
) -> None:
    """#257 / D7: `-c` / `--config-env` are dropped from global-opt extraction and rejected.

    This inverts the previous ``test_c_config_option_forwarded``: any `-c` is an
    alias-execution vector, so a benign `-c core.quotepath=false` is refused too.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "status", "args": flag_args})
    assert result.is_error is True
    assert recorder.calls == []


@pytest.mark.xfail(
    reason="green after W2: --work-tree confined to the primary repo root", strict=False
)
async def test_work_tree_outside_repo_root_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "git status", "args": ["--work-tree", OUTSIDE_DIR, "-s"]}
    )
    assert result.is_error is True
    assert OUTSIDE_DIR in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.xfail(
    reason="green after W2: --git-dir confined to the primary repo root", strict=False
)
async def test_git_dir_outside_repo_root_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "status", "args": [f"--git-dir={OUTSIDE_DIR}/.git"]}
    )
    assert result.is_error is True
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after W2: -C in the command string is confined too", strict=False)
async def test_global_opt_in_command_string_outside_repo_root_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    # Agent passes the global option as part of the `command` string.
    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": f"git -C {OUTSIDE_DIR} status", "args": []}
    )
    assert result.is_error is True
    assert OUTSIDE_DIR in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after W2: read-only subcommand allowlist", strict=False)
@pytest.mark.parametrize("subcommand", ["reset", "clean", "stash", "update-ref"])
async def test_mutating_subcommands_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subcommand: str
) -> None:
    """#257 / D7: the reviewer surface exposes read-only git only."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": subcommand})
    assert result.is_error is True
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after W2: branch is read-only on the allowlist", strict=False)
@pytest.mark.parametrize("flag", ["-D", "-d", "-m"])
async def test_branch_mutation_flags_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "branch", "args": [flag, "topic"]})
    assert result.is_error is True
    assert recorder.calls == []


@pytest.mark.parametrize(
    "subcommand",
    [
        "status",
        "log",
        "diff",
        "show",
        "rev-parse",
        "describe",
        "ls-files",
        "blame",
        "cat-file",
        "rev-list",
        "branch",
    ],
)
async def test_readonly_subcommands_allowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, subcommand: str
) -> None:
    """The D7 allowlist must keep every read-only subcommand callable."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": subcommand})
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [[subcommand]]


@pytest.mark.xfail(
    reason="green after W2: -c alias rejected regardless of payload.shell", strict=False
)
@pytest.mark.parametrize("shell", ["disabled", "restricted", "enabled"])
async def test_dash_c_alias_rejected_regardless_of_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: Shell
) -> None:
    """#257: `git -c alias.x='!cmd' status` executes shell even with shell disabled.

    `_extract_global_opts` strips `-c` into `global_opts` before the
    `_NOSHELL_BLOCKED_ARGS` scan, and that scan only walks `args` and only when
    `payload.shell == "disabled"` — so today the guard never fires.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path, shell=shell)).execute(
        {"command": "git -c alias.x='!true' status", "args": []}
    )
    assert result.is_error is True
    assert recorder.calls == []


@pytest.mark.xfail(
    reason="green after W2: -c alias in args rejected regardless of payload.shell", strict=False
)
@pytest.mark.parametrize("shell", ["disabled", "restricted", "enabled"])
async def test_dash_c_alias_in_args_rejected_regardless_of_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: Shell
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path, shell=shell)).execute(
        {"command": "status", "args": ["-c", "alias.x=!true"]}
    )
    assert result.is_error is True
    assert recorder.calls == []


class _CommitGitRecorder:
    """Serves the argv sequence ``commit_changes`` issues, recording each call."""

    def __init__(self, *, branch: str = "topic", sha: str = "abc1234") -> None:
        self.calls: list[list[str]] = []
        self.branch = branch
        self.sha = sha

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        argv = [str(a) for a in args]
        self.calls.append(argv)
        if argv == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return f"{self.branch}\n"
        if argv == ["status", "--porcelain"]:
            return " M src/mergecraft/mcp/git.py\n"
        if argv == ["rev-parse", "HEAD"]:
            return f"{self.sha}\n"
        return ""


class _PatchRecordingGitHub(GitHubClient):
    """Records Git Data ref PATCH attempts made by ``commit_changes``."""

    def __init__(self) -> None:
        super().__init__(token="test-token")
        self.patch_calls: list[str] = []

    async def patch(self, path: str, **kwargs: Any) -> Any:
        self.patch_calls.append(path)
        return {}


async def test_commit_changes_push_policy_skip_reports_pushed_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The policy-skip path already carries the honest `pushed` key."""
    recorder = _CommitGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    ctx = _ctx(tmp_path, push="disabled")
    result = await commit_changes_tool(ctx).execute({"message": "chore: wip"})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert payload["pushed"] is False


@pytest.mark.xfail(
    reason="green after W5: every commit_changes return carries pushed: bool", strict=False
)
async def test_commit_changes_always_reports_pushed_and_never_patches_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """#259 / D9: no doomed Git Data ref PATCH, and `pushed` is always present."""
    recorder = _CommitGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    github = _PatchRecordingGitHub()
    ctx = _ctx(tmp_path, push="enabled", github=github)
    result = await commit_changes_tool(ctx).execute({"message": "chore: wip"})
    assert result.is_error is False, result.content[0]["text"]
    payload = json.loads(result.content[0]["text"])
    assert isinstance(payload["pushed"], bool)
    assert payload["pushed"] is False
    assert github.patch_calls == []


@pytest.mark.xfail(
    reason="green after W5: description no longer claims a GitHub-signed commit", strict=False
)
async def test_commit_changes_description_does_not_claim_signed(tmp_path: Path) -> None:
    description = commit_changes_tool(_ctx(tmp_path)).description.lower()
    assert "signed" not in description
