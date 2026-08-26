"""GREEN — settings snapshot before publish (AG2 / MCB-19)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings import load_repo_settings
from mergecraft.config.settings_snapshot import (
    assert_config_unchanged,
    capture_repo_settings_snapshot,
    repo_settings_from_context,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _write_config(tmp_path: Path, gate_action: str) -> None:
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        f"gates:\n  gate_action: {gate_action}\n",
        encoding="utf-8",
    )


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


def test_publish_uses_the_presnapshot_settings(tmp_path: Path) -> None:
    """Publish must read the settings resolved before untrusted execution."""
    _write_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.settings.gates.gate_action == "enforce"

    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "gates:\n  gate_action: shadow\n",
        encoding="utf-8",
    )
    after = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert after.gates.gate_action == "shadow"

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    publish_mode = repo_settings_from_context(ctx).gates.gate_action
    assert publish_mode == snapshot.settings.gates.gate_action == "enforce"


def test_invalid_config_mutation_keeps_terminal_behaviour_deterministic(
    tmp_path: Path,
) -> None:
    """A config mutation after snapshot time must not change terminal verdict inputs."""
    _write_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "gates:\n  gate_action: shadow\n",
        encoding="utf-8",
    )
    second = load_repo_settings(root=tmp_path, load_learnings_files=False)
    assert snapshot.settings.gates.gate_action != second.gates.gate_action
    with pytest.raises(ValueError, match=r"config\.yaml changed"):
        assert_config_unchanged(snapshot)
