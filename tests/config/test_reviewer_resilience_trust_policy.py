"""Plan 13 W1.7 — operator trust knob RED contracts (green after W9)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mergecraft.analyzers.trust import derive_trust_tier
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import init_tool_state
from mergecraft.modes import compute_modes
from mergecraft.utils.github import GitHubClient

SAME_REPO_EVENT: dict[str, Any] = {
    "pull_request": {"head": {"repo": {"fork": False, "full_name": "acme/demo"}}}
}
FORK_EVENT: dict[str, Any] = {
    "pull_request": {"head": {"repo": {"fork": True, "full_name": "fork/demo"}}}
}


def _resolve_policy(**kwargs: Any):
    from mergecraft.config.trust_policy import resolve_trust_policy

    return resolve_trust_policy(**kwargs)


@pytest.mark.xfail(reason="green after W9: default trust policy off", strict=False)
def test_default_resolved_trust_policy_is_off(tmp_path: Path) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("analyzers:\n  enabled: true\n", encoding="utf-8")

    policy = _resolve_policy(
        event={"pull_request": {"head": {"repo": {"fork": False}}}},
        config_root=tmp_path,
        event_name="pull_request_target",
    )
    assert policy.level == "off"
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


def test_derive_trust_tier_unchanged_for_pull_request_target() -> None:
    tier = derive_trust_tier(event=SAME_REPO_EVENT, shell="restricted")
    assert tier == "untrusted"


@pytest.mark.parametrize(
    ("level", "execution", "authority"),
    [
        ("off", "untrusted", "untrusted"),
        ("analyzers", "trusted", "untrusted"),
        ("full", "trusted", "trusted"),
    ],
)
@pytest.mark.xfail(reason="green after W9: trust level pairs (D13/D14)", strict=False)
def test_trust_levels_resolve_documented_pairs(
    tmp_path: Path, level: str, execution: str, authority: str
) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"trust:\n  selfReview: {level}\n", encoding="utf-8")

    policy = _resolve_policy(
        event={"pull_request": {"head": {"repo": {"fork": False}}}},
        config_root=tmp_path,
        event_name="pull_request_target",
    )
    assert policy.level == level
    assert policy.execution_trust == execution
    assert policy.authority_trust == authority


@pytest.mark.parametrize("level", ["off", "analyzers", "full"])
@pytest.mark.xfail(reason="green after W9: fork PR unaffected at every level", strict=False)
def test_fork_pr_trust_policy_stays_untrusted(level: str, tmp_path: Path) -> None:
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"trust:\n  selfReview: {level}\n", encoding="utf-8")

    policy = _resolve_policy(
        event=FORK_EVENT, config_root=tmp_path, event_name="pull_request_target"
    )
    assert policy.execution_trust == "untrusted"
    assert policy.authority_trust == "untrusted"


@pytest.mark.xfail(reason="green after W9: analyzers level runs trusted-tier tools", strict=False)
@pytest.mark.asyncio
async def test_analyzers_level_runs_markdownlint_and_typos(tmp_path: Path) -> None:
    from mergecraft.analyzers.registry import get_manifest
    from mergecraft.analyzers.trust import evaluate_manifest_for_tier

    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(trigger="pull_request_target"),
        ),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        trust_tier="trusted",
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )
    for analyzer_id in ("markdownlint", "typos"):
        manifest = get_manifest(analyzer_id)
        decision = evaluate_manifest_for_tier(manifest, ctx)
        assert decision.skipped is False, decision.reason


@pytest.mark.xfail(reason="green after W9: analyzers level cannot APPROVE", strict=False)
@pytest.mark.asyncio
async def test_analyzers_level_blocks_create_pull_request_review_approve(
    tmp_path: Path,
) -> None:
    from mergecraft.mcp.review import create_pull_request_review_tool

    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="pull_request_target")),
        github=GitHubClient(token=""),
        github_installation_token="",
        git_token="",
        api_token="",
        authority_trust="untrusted",  # type: ignore[call-arg]
        modes=compute_modes("claude"),
        tool_state=init_tool_state(owner="acme", name="demo", dir=str(tmp_path)),
        mcp_server_url="",
        tmpdir=str(tmp_path),
    )
    result = await create_pull_request_review_tool(ctx).execute(
        {"event": "APPROVE", "body": "LGTM", "comments": []}
    )
    assert result.is_error is True


@pytest.mark.xfail(reason="green after W9: full level warns at CLI and run start", strict=False)
def test_full_trust_level_emits_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from typer.testing import CliRunner

    from mergecraft.cli.app import app

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("trust:\n  selfReview: off\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "trust",
            "set-self-review",
            "full",
            "--i-understand-this-grants-approval-authority",
            "--cwd",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "approval" in result.output.lower()


@pytest.mark.xfail(reason="green after W9: D15 PR-head edit cannot change policy", strict=False)
def test_pr_head_trust_edit_does_not_change_effective_policy(tmp_path: Path) -> None:
    from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot, config_yaml_hash

    base = tmp_path / "base"
    base.mkdir()
    base_config = base / ".mergecraft" / "config.yaml"
    base_config.parent.mkdir(parents=True)
    base_config.write_text("trust:\n  selfReview: off\n", encoding="utf-8")

    snapshot = capture_repo_settings_snapshot(root=base)
    head = tmp_path / "head"
    head.mkdir()
    head_config = head / ".mergecraft" / "config.yaml"
    head_config.parent.mkdir(parents=True)
    head_config.write_text("trust:\n  selfReview: full\n", encoding="utf-8")

    policy = _resolve_policy(
        event={"pull_request": {"head": {"repo": {"fork": False}}}},
        config_root=base,
        event_name="pull_request_target",
        settings_snapshot=snapshot,
        pr_head_config_hash=config_yaml_hash(root=head),
    )
    assert policy.level == "off"
    assert policy.resolved_from == "base_snapshot"


@pytest.mark.xfail(reason="green after W9: config hash mismatch fails closed (D15)", strict=False)
def test_config_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    from mergecraft.config.settings_snapshot import (
        assert_config_unchanged,
        capture_repo_settings_snapshot,
    )

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("trust:\n  selfReview: off\n", encoding="utf-8")
    snapshot = capture_repo_settings_snapshot(root=tmp_path)
    config.write_text("trust:\n  selfReview: full\n", encoding="utf-8")

    with pytest.raises(ValueError, match="changed after settings were snapshotted"):
        assert_config_unchanged(snapshot)


@pytest.mark.xfail(reason="green after W9: mergecraft trust show", strict=False)
def test_trust_show_reports_effective_policy_and_source(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from mergecraft.cli.app import app

    config = tmp_path / ".mergecraft" / "config.yaml"
    config.parent.mkdir(parents=True)
    config.write_text("trust:\n  selfReview: off\n", encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(app, ["trust", "show", "--cwd", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "off" in result.output.lower()
    assert "base" in result.output.lower() or "snapshot" in result.output.lower()
