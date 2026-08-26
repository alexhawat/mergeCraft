"""Fixtures for the adversarial security suite (plan W1-W4).

A *planted repo* is a real throwaway git repository with a commit and a
malicious ``post-checkout`` hook that writes a sentinel file when git executes
it — the concrete proof that hooks are on or off for a given shell mode.
"""

from __future__ import annotations

import stat
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from mergecraft.mcp.context import (
    PayloadEvent,
    RepoIdentity,
    ResolvedPayload,
    ToolContext,
)
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.types import XrepoConfig
from tests.support.run_main_harness import FakeGitHubClient

if TYPE_CHECKING:
    from pathlib import Path

SHELL_MODES = ("disabled", "restricted", "enabled")
PUSH_MODES = ("disabled", "restricted", "enabled")

HOOK_SENTINEL = "PWNED-BY-POST-CHECKOUT"


@dataclass
class PlantedRepo:
    """A real git repo with an armed ``post-checkout`` hook."""

    path: Path
    sentinel: Path


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"
    return result.stdout


@pytest.fixture
def planted_repo(tmp_path: Path) -> PlantedRepo:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "README.md").write_text("planted\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "init")

    sentinel = tmp_path / "hook-sentinel"
    hook = repo / ".git" / "hooks" / "post-checkout"
    hook.write_text(f"#!/bin/sh\necho {HOOK_SENTINEL} > {sentinel}\n", encoding="utf-8")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
    return PlantedRepo(path=repo, sentinel=sentinel)


@pytest.fixture
def make_tool_ctx(tmp_path: Path, planted_repo: PlantedRepo):
    """Factory: ToolContext pinned at ``shell`` / ``push`` for one matrix cell."""

    def _make(
        shell: str = "restricted", push: str = "restricted", *, signed_commits: bool = False
    ) -> ToolContext:
        state = init_tool_state(owner="acme", name="demo", dir=str(planted_repo.path))
        return ToolContext(
            agent_id="claude",
            repo=RepoIdentity(owner="acme", name="demo"),
            payload=ResolvedPayload(
                event=PayloadEvent(trigger="unknown"),
                shell=shell,
                push=push,
            ),
            github=FakeGitHubClient(token="test-token"),
            github_installation_token="",
            git_token="ghs_fake_cell_token",
            api_token="",
            modes=compute_modes("claude"),
            tool_state=state,
            mcp_server_url="",
            tmpdir=str(tmp_path),
            signed_commits=signed_commits,
            xrepo=XrepoConfig(mode="explicit", read=[], write=[]),
            static_checks_enabled=True,
        )

    return _make


@pytest.fixture
def make_agent_run_ctx(tmp_path: Path):
    """Factory: minimal ``AgentRunContext`` for agent env-builder inspection."""

    from mergecraft.agents.shared import AgentRunContext
    from mergecraft.mcp.tool_state import init_tool_state

    def _make() -> AgentRunContext:
        return AgentRunContext(
            payload={"shell": "restricted", "push": "restricted"},
            mcp_server_url="",
            tmpdir=str(tmp_path),
            subagent_denied_tools=(),
            instructions="review",
            tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        )

    return _make


@pytest.fixture
def no_ci_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset sandbox detection cache and use unsandboxed shell for host runs."""
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("MERGECRAFT_ALLOW_UNSANDBOXED_SHELL", "1")
    monkeypatch.setattr("mergecraft.mcp.shell._detected_sandbox", None)
    monkeypatch.setattr("mergecraft.mcp.shell._detected_netns", None)
    from mergecraft.mcp import shell as shell_mod

    monkeypatch.setattr(shell_mod, "detect_sandbox_method", lambda: "none")
