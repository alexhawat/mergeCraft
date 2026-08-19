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


@pytest.mark.parametrize("flag_args", [["-c", "core.quotepath=false", "-s"], ["--config-env=x=Y"]])
async def test_c_config_option_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, flag_args: list[str]
) -> None:
    """#257 / D7: `-c` / `--config-env` are never forwarded, they are rejected.

    Any `-c` is an alias-execution vector, so even a benign
    `-c core.quotepath=false` is refused rather than inspected.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "status", "args": flag_args})
    assert result.is_error is True
    assert recorder.calls == []


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


def _repo_and_evil_sibling(tmp_path: Path) -> tuple[Path, Path]:
    """A real repo root plus a real sibling whose name is a string prefix match.

    ``<root>-evil`` is not inside ``<root>``, but a bare textual prefix test on
    the resolved paths would accept it. Both directories are created on disk so
    ``Path.resolve()`` cannot collapse the distinction away.
    """
    root = (tmp_path / "repo").resolve()
    root.mkdir()
    evil = (tmp_path / "repo-evil").resolve()
    (evil / "secrets").mkdir(parents=True)
    return root, evil


@pytest.mark.parametrize(
    "build_args",
    [
        pytest.param(lambda p: ["-C", p], id="dash-C"),
        pytest.param(lambda p: ["--git-dir", f"{p}/.git"], id="git-dir-separate"),
        pytest.param(lambda p: [f"--git-dir={p}/.git"], id="git-dir-equals"),
        pytest.param(lambda p: ["--work-tree", p], id="work-tree-separate"),
        pytest.param(lambda p: [f"--work-tree={p}"], id="work-tree-equals"),
    ],
)
async def test_sibling_prefix_directory_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    build_args: Any,
) -> None:
    """A sibling whose path merely starts with the repo root must not be accepted."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    root, evil = _repo_and_evil_sibling(tmp_path)
    target = str(evil / "secrets")
    result = await git_tool(_ctx(root)).execute({"command": "status", "args": build_args(target)})
    assert result.is_error is True, result.content[0]["text"]
    assert target in result.content[0]["text"]
    assert recorder.calls == []


async def test_sibling_prefix_without_separator_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``<root>evil`` — a prefix match with no separator at all — is still outside."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    root = (tmp_path / "repo").resolve()
    root.mkdir()
    adjacent = (tmp_path / "repoevil").resolve()
    adjacent.mkdir()

    result = await git_tool(_ctx(root)).execute(
        {"command": "status", "args": ["-C", str(adjacent)]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert str(adjacent) in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.parametrize("suffix", ["", "/", "/."], ids=["bare", "trailing-slash", "dot"])
async def test_repo_root_itself_still_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, suffix: str
) -> None:
    """Hardening containment must not turn into a blanket refusal of the root."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    root, _evil = _repo_and_evil_sibling(tmp_path)
    given = f"{root}{suffix}"
    result = await git_tool(_ctx(root)).execute({"command": "status", "args": ["-C", given]})
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["-C", given, "status"]]


async def test_nested_path_inside_repo_root_still_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    root, _evil = _repo_and_evil_sibling(tmp_path)
    nested = root / "src" / "pkg"
    nested.mkdir(parents=True)

    result = await git_tool(_ctx(root)).execute({"command": "status", "args": ["-C", str(nested)]})
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["-C", str(nested), "status"]]


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


@pytest.mark.parametrize("shell", ["disabled", "restricted", "enabled"])
async def test_dash_c_alias_rejected_regardless_of_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: Shell
) -> None:
    """#257: `git -c alias.x='!cmd' status` is an alias-execution vector.

    Rejection must not depend on `payload.shell`: a shell-gated guard would
    leave the vector open in the `restricted`/`enabled` modes.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path, shell=shell)).execute(
        {"command": "git -c alias.x='!true' status", "args": []}
    )
    assert result.is_error is True
    assert recorder.calls == []


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


CONFIG_FLAG_MESSAGE = "can execute arbitrary code via git alias expansion"

# Single-argv `-c<name>=<value>` spellings. Upstream git parses `-c` with an
# exact `strcmp` (git.c handle_options, unchanged since v1.7.2), so git itself
# refuses these — but `_reject_config_flags` must still refuse them at the tool
# boundary rather than forwarding a config-shaped token and relying on git's
# argv parser to fail closed.
GLUED_SHORT_CONFIG_TOKENS = [
    "-calias.x=!true",
    "-cprotocol.ext.allow=always",
    "-ccore.pager=!sh",
]


@pytest.mark.xfail(reason="green after the #257 glued-config-flag fix", strict=False)
@pytest.mark.parametrize("token", GLUED_SHORT_CONFIG_TOKENS)
async def test_glued_short_config_flag_in_args_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    """#257: `-c<key>=<value>` glued into one argv token must be rejected.

    `_reject_config_flags` matches only an exact `-c` or a `-c=`-prefixed token,
    so the glued spelling is forwarded to `_run_git` untouched.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "status", "args": [token]})
    assert result.is_error is True, result.content[0]["text"]
    assert CONFIG_FLAG_MESSAGE in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after the #257 glued-config-flag fix", strict=False)
@pytest.mark.parametrize("shell", ["disabled", "restricted", "enabled"])
async def test_glued_short_config_flag_in_args_rejected_regardless_of_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: Shell
) -> None:
    """The glued spelling must be refused in every shell mode, like the spaced one."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path, shell=shell)).execute(
        {"command": "status", "args": ["-calias.x=!true"]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after the #257 glued-config-flag fix", strict=False)
@pytest.mark.parametrize("token", GLUED_SHORT_CONFIG_TOKENS)
async def test_glued_short_config_flag_in_global_opts_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    """The same token must be refused on the `global_opts` path, not just `args`.

    `--namespace` takes a separate value, so `_extract_global_opts` moves the
    following token into `global_opts` — i.e. in front of the subcommand, the
    only position where git honours a global config flag. `_reject_config_flags`
    is called on both lists and the fix has to hold for both.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "status", "args": ["--namespace", token]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert CONFIG_FLAG_MESSAGE in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.parametrize("shell", ["disabled", "restricted", "enabled"])
async def test_config_flag_in_global_opts_position_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shell: Shell
) -> None:
    """A spaced `-c` smuggled into `global_opts` via `--namespace` is already refused.

    This is the pre-subcommand position git actually honours, so the defensive
    `_reject_config_flags(global_opts)` call must keep firing here.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path, shell=shell)).execute(
        {"command": "status", "args": ["--namespace", "-c", "alias.x=!true"]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert CONFIG_FLAG_MESSAGE in result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("-c", id="bare-short"),
        pytest.param("-c=alias.x=!true", id="short-equals-attached"),
        pytest.param("--config-env", id="bare-long"),
        pytest.param("--config-env=alias.x=EVIL", id="long-equals-attached"),
    ],
)
async def test_known_config_flag_spellings_still_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    """Every spelling the current guard already catches must keep its rejection.

    `--config-env` is accepted by git both as `--config-env <name>=<envvar>` and
    as `--config-env=<name>=<envvar>`; the bare token covers the separate-value
    form. `-c` is exact-match only upstream, so `-c` and `-c=…` are the whole
    short-flag surface the guard has to keep refusing.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "status", "args": [token]})
    assert result.is_error is True, result.content[0]["text"]
    assert CONFIG_FLAG_MESSAGE in result.content[0]["text"]
    assert recorder.calls == []


async def test_spaced_config_flag_rejection_message_names_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The rejection quotes the offending token — the fix must not lose that."""
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "status", "args": ["-c", "alias.x=!true"]}
    )
    assert result.is_error is True
    text = result.content[0]["text"]
    assert "'-c'" in text
    assert CONFIG_FLAG_MESSAGE in text
    assert recorder.calls == []


@pytest.mark.parametrize(
    "token",
    [
        pytest.param("--cached", id="cached"),
        pytest.param("--column", id="column"),
        pytest.param("--color=never", id="color-equals"),
        pytest.param("--count", id="count"),
        pytest.param("--cc", id="cc"),
        pytest.param("--children", id="children"),
    ],
)
async def test_non_config_flags_beginning_with_c_still_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str
) -> None:
    """A `startswith("-c")`-style fix must not over-block legitimate flags.

    These are real read-only git flags whose names begin with `c`; none of them
    is a config flag, and blocking them would buy safety by breaking the tool.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute({"command": "log", "args": [token]})
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["log", token]]


async def test_capital_c_path_flag_is_not_a_config_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`-C` is git's path flag, not `-c`: the guard must stay case-sensitive.

    A case-insensitive or lowercased `-c` match would take `-C` down with it,
    so the confinement-checked path flag is pinned green here explicitly.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    inside = _resolved(tmp_path)
    result = await git_tool(_ctx(tmp_path)).execute({"command": "status", "args": ["-C", inside]})
    assert result.is_error is False, result.content[0]["text"]
    assert recorder.calls == [["-C", inside, "status"]]


async def test_glued_short_config_flag_in_command_string_is_not_forwarded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """In the `command` string the glued token lands as a fake subcommand.

    The read-only allowlist already refuses it, so this path is safe today; pin
    it so the glued-form fix cannot regress it into a forwarded token.
    """
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(_ctx(tmp_path)).execute(
        {"command": "git -calias.x=!true status", "args": []}
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


async def test_commit_changes_description_does_not_claim_signed(tmp_path: Path) -> None:
    description = commit_changes_tool(_ctx(tmp_path)).description.lower()
    assert "signed" not in description
