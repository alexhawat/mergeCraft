"""Unit tests for merge-attention composition (#1610)."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import make_finding
from mergecraft.classify.blast_radius import BlastRadiusClassification, LaneReason
from mergecraft.config.settings_snapshot import capture_repo_settings_snapshot
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, AgentMetadata, MergeEvidencePacket
from mergecraft.evidence.run_packet import resolve_evidence_dir
from mergecraft.mcp.context import PayloadEvent, RepoIdentity, ResolvedPayload, ToolContext
from mergecraft.mcp.tool_state import CiEvidenceState, TerminalSubmission, init_tool_state
from mergecraft.merge_attention.compose import (
    MergeAttentionInputs,
    attach_merge_attention_to_packet,
    compose_merge_attention,
    inputs_from_context,
    merge_attention_section_for_run,
)
from mergecraft.merge_attention.types import MergeAttentionSection
from mergecraft.modes import compute_modes
from mergecraft.policy.evidence_producers import EvidenceRecord, PolicyEvidence
from mergecraft.utils.github import GitHubClient


def _packet(**overrides: Any) -> MergeEvidencePacket:
    base: dict[str, Any] = dict(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="acme/demo#1",
        agent=AgentMetadata(id="x", version="0", model="m"),
        files_changed=["src/ui/Button.tsx"],
        findings=[],
        deterministic_checks=[],
    )
    base.update(overrides)
    return MergeEvidencePacket(**base)


def _write_merge_attention_config(
    tmp_path: Any,
    *,
    enabled: bool,
    include_in_packet: bool,
    display_in_summary: bool,
) -> None:
    from pathlib import Path

    root = Path(str(tmp_path))
    config_dir = root / ".mergecraft"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "config.yaml").write_text(
        f"review:\n  mergeAttention:\n"
        f"    enabled: {str(enabled).lower()}\n"
        f"    includeInPacket: {str(include_in_packet).lower()}\n"
        f"    displayInSummary: {str(display_in_summary).lower()}\n",
        encoding="utf-8",
    )


def test_compose_uses_blast_radius_for_impact() -> None:
    blast = BlastRadiusClassification(
        lane="high",
        auto_merge_lane="forbidden",
        reason="migrations",
        next_action="block",
        categories=["migrations"],
        reasons=[LaneReason(code="paths.migrations", lane="high", message="migration path")],
        checklist=[],
    )
    section = compose_merge_attention(_packet(blast_radius=blast))
    impact = next(row for row in section.axes if row.axis == "impact")
    assert impact.level == "high"
    assert section.overall == "high"


def test_policy_absent_rollback_raises_medium() -> None:
    evidence = PolicyEvidence(present={}, absent={"rollback_plan": "not declared"})
    section = compose_merge_attention(
        _packet(),
        inputs=MergeAttentionInputs(policy_evidence=evidence),
    )
    rollback = next(row for row in section.axes if row.axis == "rollback_cost")
    assert rollback.level == "medium"


def test_policy_present_health_check_lowers_error_detection() -> None:
    evidence = PolicyEvidence(
        present={
            "health_check": EvidenceRecord(
                key="health_check", source="declared-check-run", detail="ok"
            )
        },
        absent={},
    )
    section = compose_merge_attention(
        _packet(),
        inputs=MergeAttentionInputs(policy_evidence=evidence),
    )
    err = next(row for row in section.axes if row.axis == "error_detection")
    assert err.level == "low"


def test_verification_gap_for_ui_without_proof() -> None:
    section = compose_merge_attention(
        _packet(files_changed=["src/components/Panel.tsx"]),
        inputs=MergeAttentionInputs(analyzer_ran=True),
    )
    verification = next(row for row in section.axes if row.axis == "verification")
    assert verification.verification_gaps
    assert verification.level in {"medium", "high"}


def test_inputs_from_context_collects_pr_body_and_summary(tmp_path) -> None:
    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.terminal_submission = TerminalSubmission(
        id="term-1",
        verdict="approve",
        summary="Shipped with screenshot.",
        findings=[],
        payload_hash="abc123",
        submitted_at="2026-11-28T00:00:00Z",
        attempt_id=1,
    )
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(
            event=PayloadEvent(
                trigger="pull_request",
                is_pr=True,
                body="![proof](https://user-images.githubusercontent.com/1/a.png)",
            ),
        ),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )
    inputs = inputs_from_context(ctx)
    assert inputs.pr_body
    assert "proof" in inputs.pr_body
    assert inputs.review_summary == "Shipped with screenshot."


def test_inputs_from_context_scans_resolve_evidence_dir_only(tmp_path) -> None:
    """Producer-shaped base_branch rows must not feed proof; evidence dir does (MC-96982c)."""
    evidence_root = resolve_evidence_dir(tmpdir=str(tmp_path))
    evidence_root.mkdir(parents=True)
    (evidence_root / "walkthrough-demo.mp4").write_bytes(b"demo")
    (tmp_path / "stray-screenshot.png").write_bytes(b"outside evidence policy")

    state = init_tool_state(owner="acme", name="demo", dir=str(tmp_path))
    state.ci_evidence = CiEvidenceState(
        base_branch_runs=[
            {
                "ref": "main@abc1234",
                "conclusion": "success",
                "run_id": 99,
                "workflow": "CI",
                "head_sha": "abc1234567890",
                "url": "https://example.invalid/run/99",
                "fingerprint": "fp-demo",
                "source": "auto",
            },
        ]
    )
    ctx = ToolContext(
        agent_id="claude",
        repo=RepoIdentity(owner="acme", name="demo"),
        payload=ResolvedPayload(event=PayloadEvent(trigger="unknown")),
        github=GitHubClient(token="test-token"),
        github_installation_token="",
        git_token="",
        api_token="",
        modes=compute_modes("claude"),
        tool_state=state,
        mcp_server_url="",
        tmpdir=str(tmp_path),
        trust_tier="trusted",
    )
    inputs = inputs_from_context(ctx)
    paths = list(inputs.run_artifact_paths or ())
    assert "walkthrough-demo.mp4" in paths
    assert not any("stray-screenshot" in path for path in paths)
    section = compose_merge_attention(
        _packet(files_changed=["src/components/Panel.tsx"]),
        inputs=MergeAttentionInputs(analyzer_ran=True, run_artifact_paths=paths),
    )
    verification = next(row for row in section.axes if row.axis == "verification")
    assert not verification.verification_gaps


@pytest.mark.parametrize(
    ("enabled", "include_packet", "display_summary", "on_packet", "composed"),
    [
        (False, True, True, False, False),
        (True, False, False, False, False),
        (True, True, False, True, True),
        (True, False, True, False, True),
        (True, True, True, True, True),
    ],
)
def test_merge_attention_config_packet_vs_summary_independence(
    tmp_path,
    enabled: bool,
    include_packet: bool,
    display_summary: bool,
    on_packet: bool,
    composed: bool,
) -> None:
    _write_merge_attention_config(
        tmp_path,
        enabled=enabled,
        include_in_packet=include_packet,
        display_in_summary=display_summary,
    )
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    ctx = ToolContext(
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
    packet = _packet()
    attached = attach_merge_attention_to_packet(packet, ctx)
    assert (attached.merge_attention is not None) is on_packet
    section = merge_attention_section_for_run(attached, ctx)
    assert (section is not None) is composed


def test_attach_merge_attention_to_packet_when_enabled(tmp_path) -> None:
    snapshot = capture_repo_settings_snapshot(root=tmp_path, load_learnings_files=False)
    ctx = ToolContext(
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
    packet = _packet()
    attached = attach_merge_attention_to_packet(packet, ctx)
    assert attached.merge_attention is not None
    assert attached.merge_attention.overall in {"low", "medium", "high"}


def test_merge_attention_on_packet_does_not_change_decide_approval() -> None:
    finding = make_finding(
        tool="t",
        rule_id="r",
        category="Functional Correctness",
        severity="Critical",
        confidence="certain",
        message="blocker",
        path="a.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    packet = _packet(findings=[finding])
    without = decide_approval(packet, run_succeeded=True, tier="trusted")
    grade = MergeAttentionSection(
        overall="low",
        axes=compose_merge_attention(packet).axes,
    )
    with_grade = packet.model_copy(update={"merge_attention": grade})
    with_att = decide_approval(with_grade, run_succeeded=True, tier="trusted")
    assert without.verdict == with_att.verdict
