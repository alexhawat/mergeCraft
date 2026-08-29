"""W1.6 — agent roster trust boundary (wave plan 11, D9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.agents.registry import load_registry, resolve_agent_model
from mergecraft.config.settings_snapshot import (
    assert_config_unchanged,
    capture_repo_settings_snapshot,
    pinned_repo_settings_from_context,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient
from tests.cli.support_agent_roster import write_config

if TYPE_CHECKING:
    from pathlib import Path


def _tool_context(tmp_path: Path, *, snapshot: object) -> ToolContext:
    return ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
        repo_settings_snapshot=snapshot,
    )


def test_pr_head_agents_edit_cannot_change_reviewing_model(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    modelChain:
      - anthropic/claude-sonnet
""",
    )
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    registry_before = load_registry(settings=snapshot.settings, repo_root=tmp_path)
    reviewer_before = registry_before.resolve_role("reviewer")
    resolved_before = resolve_agent_model(
        reviewer_before,
        settings=snapshot.settings,
        slug_runnable=lambda _slug: True,
    )

    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        """
models:
  - anthropic/claude-sonnet
  - openai/gpt-5.3-codex
agents:
  reviewer:
    modelChain:
      - openai/gpt-5.3-codex
""".strip()
        + "\n",
        encoding="utf-8",
    )

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    pinned_settings = pinned_repo_settings_from_context(ctx)
    assert pinned_settings is not None
    registry_after = load_registry(settings=pinned_settings, repo_root=tmp_path)
    reviewer_after = registry_after.resolve_role("reviewer")
    resolved_after = resolve_agent_model(
        reviewer_after,
        settings=pinned_settings,
        slug_runnable=lambda _slug: True,
    )
    assert resolved_after.requested_model == resolved_before.requested_model
    assert resolved_after.requested_model == "anthropic/claude-sonnet"


def test_config_hash_mismatch_during_read_only_run_fails_closed(tmp_path: Path) -> None:
    write_config(tmp_path, "models:\n  - anthropic/claude-sonnet\n")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "models:\n  - openai/gpt-5.3-codex\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match=r"config\.yaml changed"):
        assert_config_unchanged(snapshot)
