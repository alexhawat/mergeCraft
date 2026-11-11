"""``upload_file``, ``git ls-remote`` and the shell share one resolved path denylist.

Each tool resolves a caller-named path before matching, refuses git credential
material and the askpass tree, and refuses operands outside the workspace.
Repositories are real git in ``tmp_path``.
"""

from __future__ import annotations

import asyncio
import subprocess
from typing import TYPE_CHECKING, Any

import pytest
from tests.mcp.test_git_tool import _ctx
from tests.support.policy_fixtures import commit_all, init_git_repo

from mergecraft.mcp.git import git_tool
from mergecraft.mcp.git_guards import shell_command_denies_credential_paths
from mergecraft.mcp.upload import upload_file_tool
from mergecraft.utils.path_confinement import is_denied_credential_path

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.mcp.context import ToolContext


def _checkout(tmp_path: Path) -> Path:
    root = (tmp_path / "checkout").resolve()
    init_git_repo(root)
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    commit_all(root, "initial")
    return root


def _upload_ctx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ToolContext, Path]:
    monkeypatch.delenv("MERGECRAFT_API_URL", raising=False)
    monkeypatch.delenv("MERGECRAFT_TEMP_DIR", raising=False)
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path / "checkout"))
    root = _checkout(tmp_path)
    ctx = _ctx(root)
    scratch = (tmp_path / "scratch").resolve()
    (scratch / "credentials").mkdir(parents=True)
    (scratch / "credentials" / "helper").write_text("x\n", encoding="utf-8")
    (scratch / "artifact.txt").write_text("evidence\n", encoding="utf-8")
    ctx.tmpdir = str(scratch)
    return ctx, root


@pytest.mark.parametrize(
    "build",
    [
        pytest.param(lambda r, _s: r / ".git" / "config", id="git-config"),
        pytest.param(lambda r, _s: r / ".git" / "objects" / ".." / "config", id="dotdot"),
        pytest.param(lambda _r, s: s / "credentials" / "helper", id="askpass-tree"),
    ],
)
async def test_upload_refuses_credential_material(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, build: Any
) -> None:
    ctx, root = await asyncio.to_thread(_upload_ctx, tmp_path, monkeypatch)
    target = build(root, tmp_path / "scratch")
    result = await upload_file_tool(ctx).execute({"path": str(target)})
    assert result.is_error is True
    assert "credential material" in result.content[0]["text"]


async def test_upload_refuses_out_of_workspace_and_accepts_allowed_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, root = await asyncio.to_thread(_upload_ctx, tmp_path, monkeypatch)
    outside = tmp_path / "outside.txt"
    outside.write_text("x\n", encoding="utf-8")
    refused = await upload_file_tool(ctx).execute({"path": str(outside)})
    assert refused.is_error is True
    for allowed in (root / "README.md", tmp_path / "scratch" / "artifact.txt"):
        result = await upload_file_tool(ctx).execute({"path": str(allowed)})
        assert result.is_error is False, result.content[0]["text"]


def _ls_remote_setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ToolContext, Path]:
    monkeypatch.setenv("GITHUB_WORKSPACE", str(tmp_path))
    root = _checkout(tmp_path)
    remote = (tmp_path / "remote.git").resolve()
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(root), str(remote)], check=True, capture_output=True
    )
    subprocess.run(
        ["git", "remote", "add", "origin", str(remote)], cwd=root, check=True, capture_output=True
    )
    stray = (tmp_path / "stray").resolve()
    init_git_repo(stray)
    return _ctx(root), stray


@pytest.mark.parametrize(
    "operand",
    [
        pytest.param(lambda s: [str(s)], id="absolute"),
        pytest.param(lambda _s: ["../stray"], id="relative"),
        pytest.param(lambda s: [f"file://{s}"], id="file-url"),
        pytest.param(lambda s: ["--heads", "--", str(s)], id="after-dashdash"),
        pytest.param(lambda _s: ["https://example.invalid/acme/demo.git"], id="network"),
        pytest.param(lambda _s: [".git/config"], id="credential"),
    ],
)
async def test_ls_remote_refuses_other_repositories(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operand: Any
) -> None:
    ctx, stray = await asyncio.to_thread(_ls_remote_setup, tmp_path, monkeypatch)
    result = await git_tool(ctx).execute({"command": "ls-remote", "args": operand(stray)})
    assert result.is_error is True
    assert "Blocked" in result.content[0]["text"]


@pytest.mark.parametrize(
    "args",
    [
        pytest.param([], id="no-operand"),
        pytest.param(["origin"], id="origin"),
        pytest.param(["--heads", "origin"], id="origin-with-flag"),
        pytest.param(["."], id="own-checkout"),
    ],
)
async def test_ls_remote_allows_origin_and_own_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, args: list[str]
) -> None:
    ctx, _stray = await asyncio.to_thread(_ls_remote_setup, tmp_path, monkeypatch)
    result = await git_tool(ctx).execute({"command": "ls-remote", "args": args})
    assert result.is_error is False, result.content[0]["text"]


def _credential_tree(tmp_path: Path) -> Path:
    root = tmp_path / "checkout"
    (root / ".git").mkdir(parents=True)
    (root / ".git" / "config").write_text("[core]\n", encoding="utf-8")
    (root / "README.md").write_text("hi\n", encoding="utf-8")
    return root


@pytest.mark.parametrize(
    "command",
    [
        "cd .git && cat config",
        "cd .git; cat ./config",
        "pushd .git >/dev/null; head -5 config",
        "cat .git/conf*",
        "cat .git/c?nfig",
        "cat .GIT/config",
        "cat .git/./config",
    ],
)
def test_shell_check_resolves_before_matching(tmp_path: Path, command: str) -> None:
    root = _credential_tree(tmp_path)
    assert (
        shell_command_denies_credential_paths(command, tmpdir=str(tmp_path), cwd=str(root))
        is not None
    )


@pytest.mark.parametrize("command", ["cat README.md", "cd src && ls", "grep -rn config ."])
def test_shell_check_allows_ordinary_commands(tmp_path: Path, command: str) -> None:
    root = _credential_tree(tmp_path)
    (root / "src").mkdir()
    assert (
        shell_command_denies_credential_paths(command, tmpdir=str(tmp_path), cwd=str(root)) is None
    )


def test_denylist_matches_by_file_identity(tmp_path: Path) -> None:
    root = _credential_tree(tmp_path)
    link = tmp_path / "alias"
    link.symlink_to(root / ".git" / "config")
    assert is_denied_credential_path(str(link), cwd=str(tmp_path), checkout_roots=[str(root)])
    assert not is_denied_credential_path("README.md", cwd=str(root))
