"""Unit tests for merge-attention composition (#1610)."""

from __future__ import annotations

from typing import Any

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import make_finding
from mergecraft.classify.blast_radius import BlastRadiusClassification, LaneReason
from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, AgentMetadata, MergeEvidencePacket
from mergecraft.merge_attention.compose import MergeAttentionInputs, compose_merge_attention
from mergecraft.merge_attention.types import MergeAttentionSection
from mergecraft.policy.evidence_producers import EvidenceRecord, PolicyEvidence


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
