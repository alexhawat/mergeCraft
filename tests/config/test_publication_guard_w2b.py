"""W2b Step 3 — publication guard re-baseline (#584, D14/D16)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from mergecraft.config.settings_snapshot import (
    assert_config_unchanged,
    capture_repo_settings_snapshot,
    config_yaml_hash,
    rebaseline_repo_settings_snapshot,
    repo_settings_from_context,
)
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

if TYPE_CHECKING:
    from pathlib import Path


def _write_gate_config(tmp_path: Path, gate_action: str) -> None:
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


def test_checkout_pr_tree_swap_publishes_normally(tmp_path: Path) -> None:
    """#582 regression — checkout_pr tree swap with rebaseline does not block publication."""
    _write_gate_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.settings.gates.gate_action == "enforce"

    # Simulate checkout_pr materializing the PR head on the same workspace root.
    (tmp_path / "README.md").write_text("pr head content\n", encoding="utf-8")

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    rebaseline_repo_settings_snapshot(ctx)

    publish_gate = repo_settings_from_context(ctx).gates.gate_action
    assert publish_gate == "enforce"


def test_config_edit_after_rebaseline_refuses(tmp_path: Path) -> None:
    """Edits to .mergecraft/config.yaml after the checkout re-baseline still fail closed."""
    _write_gate_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    rebaseline_repo_settings_snapshot(ctx)

    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "gates:\n  gate_action: shadow\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match=r"config\.yaml changed"):
        assert_config_unchanged(ctx.repo_settings_snapshot)
    with pytest.raises(ValueError, match=r"config\.yaml changed"):
        repo_settings_from_context(ctx)


def test_snapshot_without_config_file_does_not_fail_closed(tmp_path: Path) -> None:
    """An absent config at snapshot time is not treated as a mismatch when config appears later."""
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.config_hash == ""

    _write_gate_config(tmp_path, "enforce")
    assert config_yaml_hash(root=tmp_path) != ""

    assert_config_unchanged(snapshot)

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    publish_gate = repo_settings_from_context(ctx).gates.gate_action
    assert publish_gate == snapshot.settings.gates.gate_action


def test_pr_config_edit_in_diff_publishes_with_pinned_settings(tmp_path: Path) -> None:
    """#562 — a PR that legitimately edits config publishes using the re-baselined snapshot."""
    _write_gate_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.settings.gates.gate_action == "enforce"

    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "gates:\n  gate_action: shadow\n",
        encoding="utf-8",
    )
    assert config_yaml_hash(root=tmp_path) != snapshot.config_hash

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    with pytest.raises(ValueError, match=r"config\.yaml changed"):
        repo_settings_from_context(ctx)

    rebaseline_repo_settings_snapshot(ctx)

    publish_gate = repo_settings_from_context(ctx).gates.gate_action
    assert publish_gate == "enforce"
    assert publish_gate != "shadow"


def test_rebaseline_carries_operator_owned_provenance_forward(tmp_path: Path) -> None:
    """A rebaseline with a prior snapshot carries ``operator_owned`` forward unchanged.

    Mirrors the production ``pull_request_target`` path: ``main.py`` stamps
    the run-start snapshot ``operator_owned=True`` before ``checkout_pr``
    ever runs; the rebaseline after checkout must not silently drop that
    provenance even though it re-derives ``config_hash``/``repo_root`` from
    the (now PR-head) checkout.
    """
    _write_gate_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(
        root=tmp_path, load_learnings_files=False, operator_owned=True
    )
    assert snapshot.operator_owned is True

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    rebaselined = rebaseline_repo_settings_snapshot(ctx)

    assert rebaselined.operator_owned is True
    assert ctx.repo_settings_snapshot is not None
    assert ctx.repo_settings_snapshot.operator_owned is True


def test_rebaseline_with_no_prior_snapshot_is_never_operator_owned(tmp_path: Path) -> None:
    """D7 (#622 Task 2) — a rebaseline with no prior snapshot fails closed.

    Some callers (e.g. local ``mcp serve``) never install a run-scope
    snapshot before invoking ``checkout_pr``. When that happens,
    ``rebaseline_repo_settings_snapshot`` falls back to a live load off
    whatever is on disk — which, post-checkout, may already be a fork's own
    HEAD. Even if that on-disk YAML claims ``exportUntrustedContent: true``,
    the resulting snapshot must never be marked operator-owned: only a
    snapshot carried forward from a genuine pre-checkout capture may lift
    the D7 cap.
    """
    config_dir = tmp_path / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        "tracing:\n  exportUntrustedContent: true\n",
        encoding="utf-8",
    )

    ctx = _tool_context(tmp_path, snapshot=None)
    assert ctx.repo_settings_snapshot is None

    rebaselined = rebaseline_repo_settings_snapshot(ctx)

    assert rebaselined.settings.tracing.export_untrusted_content is True
    assert rebaselined.operator_owned is False
    assert ctx.repo_settings_snapshot is not None
    assert ctx.repo_settings_snapshot.operator_owned is False


def test_capture_repo_settings_snapshot_defaults_to_not_operator_owned(
    tmp_path: Path,
) -> None:
    """Fail closed by default — a caller that doesn't reason about provenance gets ``False``."""
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.operator_owned is False
