"""GREEN — settings snapshot before publish (AG2 / MCB-19)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from tests.support.policy_fixtures import rule, write_policy

from mergecraft.config.settings import load_repo_settings
from mergecraft.config.settings_snapshot import (
    assert_config_unchanged,
    capture_repo_settings_snapshot,
    rebaseline_repo_settings_snapshot,
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
        trust_tier="trusted",
    )


def test_publish_uses_the_presnapshot_settings(tmp_path: Path) -> None:
    """Publish must read the settings resolved before untrusted execution."""
    _write_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    assert snapshot.settings.gates.gate_action == "enforce"

    ctx = _tool_context(tmp_path, snapshot=snapshot)
    publish_mode = repo_settings_from_context(ctx).gates.gate_action
    assert publish_mode == snapshot.settings.gates.gate_action == "enforce"


@pytest.mark.parametrize("head_cap", [0, 99])
def test_round_cap_uses_base_settings_after_checkout(tmp_path: Path, head_cap: int) -> None:
    from mergecraft.evidence.findings import load_run_findings_with_drops
    from mergecraft.mcp.checkout import _annotate_review_round

    _write_config(tmp_path, "enforce")
    config = tmp_path / ".mergecraft" / "config.yaml"
    config.write_text("review:\n  maxReviewRounds: 3\n", encoding="utf-8")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, operator_owned=True)
    ctx = _tool_context(tmp_path, snapshot=snapshot)
    ctx.tool_state.review_round_index = 4

    config.write_text(f"review:\n  maxReviewRounds: {head_cap}\n", encoding="utf-8")
    rebaseline_repo_settings_snapshot(ctx)
    result: dict[str, object] = {}
    _annotate_review_round(result, round_index=4, ctx=ctx)
    assert result == {
        "reviewRoundIndex": 4,
        "maxReviewRounds": 3,
        "reviewRoundCapExceeded": True,
    }

    findings, dropped = load_run_findings_with_drops(ctx)
    assert dropped == 0
    assert [finding.rule_id for finding in findings] == ["review-round-cap-exceeded"]
    assert ctx.tool_state.review_round_cap_announced
    assert load_run_findings_with_drops(ctx) == ([], 0)


@pytest.mark.parametrize(("round_index", "already_posted"), [(3, False), (4, True)])
def test_round_cap_loader_skips_ineligible_runs(
    tmp_path: Path, round_index: int, already_posted: bool
) -> None:
    from mergecraft.evidence.findings import load_run_findings_with_drops

    snapshot = capture_repo_settings_snapshot(root=tmp_path)
    ctx = _tool_context(tmp_path, snapshot=snapshot)
    ctx.tool_state.review_round_index = round_index
    ctx.tool_state.review_round_cap_announced = already_posted

    assert load_run_findings_with_drops(ctx) == ([], 0)
    assert ctx.tool_state.review_round_cap_announced == already_posted


def test_publish_refuses_when_config_mutates_after_snapshot(tmp_path: Path) -> None:
    """A config mutation after snapshot time must not change publish/gate inputs."""
    _write_config(tmp_path, "enforce")
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    (tmp_path / ".mergecraft" / "config.yaml").write_text(
        "gates:\n  gate_action: shadow\n",
        encoding="utf-8",
    )
    ctx = _tool_context(tmp_path, snapshot=snapshot)
    with pytest.raises(ValueError, match=r"config\.yaml changed"):
        repo_settings_from_context(ctx)


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


def test_the_snapshot_carries_the_repository_policy(tmp_path: Path) -> None:
    """The rules a review will apply are pinned with the settings, not re-read later."""
    _write_config(tmp_path, "enforce")
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope={"path": "src/billing/**"})])

    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)

    assert snapshot.policy is not None
    assert [item.id for item in snapshot.policy.rules] == ["billing.no-secret"]
    assert snapshot.policy.source_path == ".mergecraft/policy/rules.yaml"
    assert snapshot.policy.sha256
    assert snapshot.policy.load_error is None


def test_rebaseline_preserves_the_run_start_policy(tmp_path: Path) -> None:
    """``checkout_pr`` rewrites the working tree; it must not rewrite the rules."""
    _write_config(tmp_path, "enforce")
    write_policy(
        tmp_path,
        rules=[
            rule(
                "billing.no-secret",
                severity="Major",
                enforcement="blocking",
                scope={"path": "src/billing/**"},
            )
        ],
    )
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    ctx = _tool_context(tmp_path, snapshot=snapshot)

    # checkout_pr materializes a PR head that weakens the rule on disk.
    write_policy(
        tmp_path,
        rules=[
            rule(
                "billing.no-secret",
                severity="Minor",
                enforcement="advisory",
                scope={"path": "src/billing/**"},
            )
        ],
    )
    rebaselined = rebaseline_repo_settings_snapshot(ctx)

    assert rebaselined.policy is not None
    assert rebaselined.policy.rules[0].enforcement == "blocking"
    assert rebaselined.policy == snapshot.policy


def test_a_pull_request_target_capture_is_operator_owned(tmp_path: Path) -> None:
    """The provenance that protects settings protects the policy the same way."""
    _write_config(tmp_path, "enforce")
    write_policy(tmp_path, rules=[rule("billing.no-secret", scope={"path": "src/billing/**"})])

    snapshot = capture_repo_settings_snapshot(
        root=tmp_path,
        load_learnings_files=False,
        operator_owned=True,
    )

    assert snapshot.operator_owned is True
    assert snapshot.policy is not None
    assert snapshot.policy.operator_owned is True
