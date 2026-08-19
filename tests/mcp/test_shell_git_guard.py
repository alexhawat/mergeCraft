"""The ``shell`` tool must never run git — every invocation form (#257 ingress 3).

``shell_tool`` refuses git because the dedicated git tools are where the #257
alias/config guard and the path confinement live, and neither applies to a
string handed to ``bash -c``. The tool is registered whenever
``payload.shell == "restricted"``, so any spelling that slips past
``_is_git_command`` is a full bypass of the git tool's hardening — including
``git -c alias.z='!sh -c …' z`` and the ``git clean`` / ``filter-branch``
verbs the git tool refuses by name.

The original separator class was ``[;&|]``, which does not contain a newline:
``bash -c`` runs every line of its argument, so ``echo x\\ngit …`` reached the
shell untouched. Command substitution, absolute paths, and wrapper commands
were unmatched for the same reason — the guard modelled one spelling of
"another command follows" rather than the space of them.

These cases pin the **predicate**, not a regex: they say which strings must be
refused and which must keep running, so any implementation that gets the
boundary right passes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.shell import _is_git_command, shell_tool
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

Shell = Literal["disabled", "restricted", "enabled"]


def _ctx(tmp_path: Path, *, shell: Shell = "restricted") -> ToolContext:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request"), shell=shell, push="restricted"
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )


# The alias payload the git tool refuses outright (#257): if any of these reach
# `bash -c`, the guard the PR claims to have sealed is bypassed entirely.
ALIAS_PAYLOAD = "git -c alias.z='!sh -c \"id\"' z"

BYPASSES = [
    pytest.param(f"echo x\n{ALIAS_PAYLOAD}", id="newline-separator"),
    pytest.param("echo x\ngit clean -fdx", id="newline-git-clean"),
    pytest.param("echo x\r\ngit status", id="crlf-separator"),
    pytest.param("echo $(git rev-parse HEAD)", id="command-substitution"),
    pytest.param("echo `git rev-parse HEAD`", id="backtick-substitution"),
    pytest.param("/usr/bin/git status", id="absolute-path"),
    pytest.param("./git status", id="relative-path"),
    pytest.param("env git status", id="env-wrapper"),
    pytest.param("env GIT_DIR=/tmp/x git status", id="env-assignment-wrapper"),
    pytest.param("GIT_DIR=/tmp/x git status", id="bare-assignment-prefix"),
    pytest.param("xargs git checkout", id="xargs-wrapper"),
    pytest.param("xargs -n1 git checkout", id="xargs-with-flag"),
    pytest.param("bash -c 'git filter-branch --all'", id="nested-bash"),
    pytest.param("sh -c 'git status'", id="nested-sh"),
    pytest.param("( git status )", id="subshell"),
    pytest.param("timeout 5 git status", id="timeout-wrapper"),
    pytest.param("nohup git push &", id="nohup-wrapper"),
]

# Separator spellings the original class did cover — regression guards, so a
# rewrite cannot trade the new coverage for the old.
KNOWN_SEPARATORS = [
    pytest.param("echo x; git status", id="semicolon"),
    pytest.param("echo x && git status", id="and-and"),
    pytest.param("echo x || git status", id="or-or"),
    pytest.param("echo x | git apply", id="pipe"),
    pytest.param("git status", id="bare"),
    pytest.param("git", id="bare-no-args"),
    pytest.param("sudo git status", id="sudo"),
    pytest.param("echo x; sudo git status", id="separator-then-sudo"),
]

# Commands that contain the letters "git" but invoke something else. Buying
# safety by refusing these would break the tool for no gain.
NOT_GIT = [
    pytest.param("grep git README.md", id="git-as-grep-pattern"),
    pytest.param("ls -la .git", id="dot-git-directory"),
    pytest.param("echo 'use the git tool'", id="git-inside-a-string"),
    pytest.param('echo "ASKPASS=[$GIT_ASKPASS]"', id="uppercase-env-var"),
    pytest.param('echo "TOK=[${GITHUB_TOKEN:-empty}]"', id="github-token-var"),
    pytest.param("cat docs/git.md", id="filename-containing-git"),
    pytest.param("env", id="bare-env"),
    pytest.param("printenv", id="printenv"),
    pytest.param("pwd", id="pwd"),
    pytest.param("cat /proc/1/environ 2>/dev/null; cat /proc/self/environ", id="proc-scrape"),
    pytest.param("./gitlab-runner --version", id="prefix-not-basename"),
    pytest.param("python -m pytest tests/mcp -q", id="pytest"),
]


@pytest.mark.parametrize("command", BYPASSES)
def test_git_invocation_forms_are_recognised(command: str) -> None:
    """Every form the shell would run as git must be recognised as git."""
    assert _is_git_command(command) is True, command


@pytest.mark.parametrize("command", KNOWN_SEPARATORS)
def test_already_covered_forms_stay_recognised(command: str) -> None:
    assert _is_git_command(command) is True, command


@pytest.mark.parametrize("command", NOT_GIT)
def test_non_git_commands_are_not_over_blocked(command: str) -> None:
    assert _is_git_command(command) is False, command


@pytest.mark.parametrize("command", BYPASSES)
@pytest.mark.parametrize("shell", ["restricted", "enabled"])
async def test_shell_tool_refuses_every_git_form(
    tmp_path: Path, command: str, shell: Shell
) -> None:
    """End-to-end: the refusal happens before anything reaches ``bash -c``.

    Parametrized over both shell modes the tool is registered in — the deleted
    ``_NOSHELL_BLOCKED_ARGS`` gate treated ``shell`` as the larger hole, and
    that is exactly the mode this must hold in.
    """
    result = await shell_tool(_ctx(tmp_path, shell=shell)).execute(
        {"command": command, "description": "git bypass attempt"}
    )
    assert result.is_error is True, result.content[0]["text"]
    assert "git commands are not allowed" in result.content[0]["text"]
