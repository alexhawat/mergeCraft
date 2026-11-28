"""Render tests for merge-attention blocks."""

from __future__ import annotations

from mergecraft.evidence.packet import PACKET_SCHEMA_VERSION, AgentMetadata, MergeEvidencePacket
from mergecraft.merge_attention.compose import compose_merge_attention
from mergecraft.merge_attention.render import (
    merge_attention_record_lines,
    merge_attention_summary_block,
)


def _packet() -> MergeEvidencePacket:
    return MergeEvidencePacket(
        schema_version=PACKET_SCHEMA_VERSION,
        change_id="acme/demo#2",
        agent=AgentMetadata(id="x", version="0", model="m"),
        files_changed=["README.md"],
        findings=[],
        deterministic_checks=[],
    )


def test_summary_block_contains_overall_and_axes() -> None:
    block = merge_attention_summary_block(compose_merge_attention(_packet()))
    assert "Merge-attention grade" in block
    assert "**Overall:** `" in block
    assert "Alignment" in block
    assert "does not gate merge" in block


def test_record_lines_are_prefixed_bullets() -> None:
    lines = merge_attention_record_lines(compose_merge_attention(_packet()))
    assert lines[0].startswith("- **Merge-attention:**")
    assert any(line.startswith("  - Verification:") for line in lines)
