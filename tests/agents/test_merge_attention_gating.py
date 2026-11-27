"""Prove merge-attention never feeds merge gates (#1609)."""

from __future__ import annotations

from typing import Any

from tests.evidence.support import sample_minimal_packet_dict

from mergecraft.agents.gates import decide_approval, select_rule_id
from mergecraft.evidence.packet import MergeEvidencePacket
from mergecraft.merge_attention.compose import compose_merge_attention


def _packet(**overrides: Any) -> MergeEvidencePacket:
    base = sample_minimal_packet_dict()
    base.update(overrides)
    return MergeEvidencePacket(**base)


def test_select_rule_id_ignores_merge_attention() -> None:
    packet = _packet()
    with_grade = packet.model_copy(update={"merge_attention": compose_merge_attention(packet)})
    assert select_rule_id(packet) == select_rule_id(with_grade)


def test_decide_approval_ignores_high_merge_attention() -> None:
    from mergecraft.classify.blast_radius import BlastRadiusClassification, LaneReason

    blast = BlastRadiusClassification(
        lane="high",
        auto_merge_lane="forbidden",
        reason="migrations",
        next_action="block",
        categories=["migrations"],
        reasons=[LaneReason(code="paths.migrations", lane="high", message="migration path")],
        checklist=[],
    )
    packet = _packet(blast_radius=blast)
    stamped = packet.model_copy(update={"merge_attention": compose_merge_attention(packet)})
    assert (
        decide_approval(packet, run_succeeded=True, tier="trusted").verdict
        == decide_approval(stamped, run_succeeded=True, tier="trusted").verdict
    )
