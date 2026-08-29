"""Plan 13 W1.1 — git tool containment RED contracts (green after W2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tests.mcp.reviewer_resilience_support import git_ctx, init_git_repo, tool_error_text

from mergecraft.mcp.git import git_tool
from mergecraft.mcp.git_guards import _READONLY_SUBCOMMANDS

OUTSIDE = "/github/outside"


class _RunGitRecorder:
    def __init__(self, *, fail_stderr: str = "", output: str = "ok") -> None:
        self.calls: list[list[str]] = []
        self.fail_stderr = fail_stderr
        self.output = output

    def __call__(self, args: list[str], *, cwd: str, env: dict[str, str] | None = None) -> str:
        self.calls.append([str(a) for a in args])
        if self.fail_stderr:
            from mergecraft.mcp import git as git_mod

            raise RuntimeError(
                f"git {' '.join(args)} failed (128): {self.fail_stderr}\n{git_mod._AUTH_FAILURE_HINT}"
            )
        return self.output


@pytest.mark.parametrize(
    "subcommand",
    sorted(_READONLY_SUBCOMMANDS),
)
@pytest.mark.parametrize(
    "no_index_flag",
    ["--no-index", "--no-index=/tmp/x", "--no-index=."],
    ids=["bare", "equals-path", "equals-dot"],
)
@pytest.mark.xfail(reason="green after W2: refuse --no-index on all subcommands", strict=False)
@pytest.mark.asyncio
async def test_no_index_refused_for_allowlisted_subcommands(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    subcommand: str,
    no_index_flag: str,
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    args = [no_index_flag, "--", "/dev/null", str(tmp_path / ".git" / "config")]
    if no_index_flag.startswith("--no-index="):
        args = [no_index_flag, "--", "/dev/null", str(tmp_path / ".git" / "config")]

    result = await git_tool(git_ctx(tmp_path)).execute({"command": subcommand, "args": args})
    assert result.is_error is True, result.content[0]["text"]
    assert "no-index" in tool_error_text(result).lower()
    assert recorder.calls == []


@pytest.mark.parametrize(
    ("args", "outside"),
    [
        (["--", OUTSIDE], "after --"),
        ([OUTSIDE], "before --"),
    ],
)
@pytest.mark.xfail(reason="green after W2: confine positional paths", strict=False)
@pytest.mark.asyncio
async def test_positional_path_outside_workspace_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    args: list[str],
    outside: str,
) -> None:
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    result = await git_tool(git_ctx(tmp_path)).execute({"command": "show", "args": args})
    assert result.is_error is True, result.content[0]["text"]
    assert OUTSIDE in tool_error_text(result)
    assert recorder.calls == []


@pytest.mark.parametrize(
    "target",
    [
        ".git/config",
        ".git/credentials",
    ],
)
@pytest.mark.xfail(reason="green after W2: deny credential paths", strict=False)
@pytest.mark.asyncio
async def test_credential_git_paths_refused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
) -> None:
    init_git_repo(tmp_path)
    cred_path = tmp_path / target
    if target.endswith("credentials"):
        cred_path.parent.mkdir(parents=True, exist_ok=True)
        cred_path.write_text("https://x-access-token:ghp_deadbeef@github.com\n", encoding="utf-8")

    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    result = await git_tool(git_ctx(tmp_path)).execute(
        {"command": "show", "args": [f"HEAD:{target}"]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert target.split("/")[-1] in tool_error_text(result)
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after W2: deny askpass tree", strict=False)
@pytest.mark.asyncio
async def test_askpass_path_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    askpass_dir = tmp_path / "credentials"
    askpass_dir.mkdir()
    askpass = askpass_dir / "git-askpass.sh"
    askpass.write_text("#!/bin/sh\necho token\n", encoding="utf-8")

    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)
    result = await git_tool(git_ctx(tmp_path)).execute(
        {"command": "show", "args": [f"HEAD:{askpass}"]}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert (
        "askpass" in tool_error_text(result).lower()
        or "credential" in tool_error_text(result).lower()
    )
    assert recorder.calls == []


@pytest.mark.xfail(reason="green after W2: redact git failure stderr", strict=False)
@pytest.mark.asyncio
async def test_git_failure_stderr_token_redacted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    init_git_repo(tmp_path)
    token = "ghp_1234567890abcdefghijklmnopqrstuvwxyz12"
    recorder = _RunGitRecorder(fail_stderr=f"fatal: Authorization failed for token {token}")
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(tmp_path)).execute({"command": "status"})
    text = tool_error_text(result)
    assert token not in text
    assert "ghp_" not in text or "***" in text


@pytest.mark.xfail(reason="green after W2: reproduce run 33126460925 refusal", strict=False)
@pytest.mark.asyncio
async def test_run_33126460925_no_index_git_config_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "github" / "workspace"
    init_git_repo(workspace)
    recorder = _RunGitRecorder()
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(workspace)).execute(
        {
            "command": "diff",
            "args": [
                "--no-index",
                "--",
                "/dev/null",
                "/github/workspace/.git/config",
            ],
        }
    )
    assert result.is_error is True, result.content[0]["text"]
    assert recorder.calls == []


@pytest.mark.parametrize(
    ("command", "args", "expected_prefix"),
    [
        (
            "diff",
            ["--merge-base", "origin/main", "HEAD"],
            ["diff", "--merge-base", "origin/main", "HEAD"],
        ),
        ("show", ["deadbeef:README.md"], ["show", "deadbeef:README.md"]),
        ("ls-files", ["-co"], ["ls-files", "-co"]),
        ("branch", ["-av"], ["branch", "-av"]),
    ],
)
@pytest.mark.asyncio
async def test_legitimate_readonly_invocations_still_forwarded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    args: list[str],
    expected_prefix: list[str],
) -> None:
    init_git_repo(tmp_path)
    recorder = _RunGitRecorder(output="ok\n")
    monkeypatch.setattr("mergecraft.mcp.git._run_git", recorder)

    result = await git_tool(git_ctx(tmp_path)).execute({"command": command, "args": args})
    payload = json.loads(result.content[0]["text"])
    assert result.is_error is False, result.content[0]["text"]
    assert "ok" in payload["output"]
    assert recorder.calls == [expected_prefix]
