"""CF4.4 — the comment footer's run link honours ``GITHUB_SERVER_URL`` (D15).

``mcp/comment.py`` hard-coded ``https://github.com`` when building the run
link, so a GitHub Enterprise install produced a dead link. The web host now
comes from the shared server-URL helper, defaulting to github.com.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mergecraft.mcp.comment import _footer
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    import pytest


def _ctx(tmp_path: Path, *, run_id: int | None) -> ToolContext:
    repo_root = tmp_path / "repo"
    scratch = tmp_path / "scratch"
    repo_root.mkdir()
    scratch.mkdir()
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(repo_root)),
        mcp_server_url="",
        tmpdir=str(scratch),
        run_id=run_id,
        trust_tier="trusted",
    )


def test_footer_run_link_honours_github_server_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_SERVER_URL", "https://ghe.example")
    footer = _footer(_ctx(tmp_path, run_id=42))
    assert "https://ghe.example/acme/demo/actions/runs/42" in footer
    assert "github.com" not in footer


def test_footer_run_link_defaults_to_public_github(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("GITHUB_SERVER_URL", raising=False)
    footer = _footer(_ctx(tmp_path, run_id=42))
    assert "https://github.com/acme/demo/actions/runs/42" in footer
