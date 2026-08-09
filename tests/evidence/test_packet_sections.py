"""Merge Evidence Packet — required sections and nullable-until-later fields (WA-T.4)."""

from __future__ import annotations

from tests.evidence.support import import_module

_REQUIRED_SECTIONS: tuple[str, ...] = (
    "schema_version",
    "change_id",
    "agent",
    "files_changed",
    "deterministic_checks",
    "decision",
)


_NULLABLE_UNTIL_LATER: tuple[str, ...] = (
    "blast_radius",  # nullable until Batch B (W5)
    "trajectory",  # nullable until Batch C (W7)
    "evals",  # nullable until Batch E (W11)
)


def test_packet_contains_required_sections() -> None:
    """Every required top-level section is present on the packet model."""
    packet_mod = import_module("mergecraft.evidence.packet")
    fields = packet_mod.MergeEvidencePacket.model_fields
    for name in _REQUIRED_SECTIONS:
        assert name in fields, f"required section {name!r} missing from packet"


def test_packet_contains_nullable_until_later_sections() -> None:
    """Nullable-until-later sections are present and typed ``| None`` (not omitted)."""
    packet_mod = import_module("mergecraft.evidence.packet")
    fields = packet_mod.MergeEvidencePacket.model_fields
    for name in _NULLABLE_UNTIL_LATER:
        assert name in fields, f"nullable-until-later section {name!r} missing from packet"
        # Nullable fields must accept ``None`` as a value — i.e. their
        # default must be ``None`` or their annotation must include ``None``.
        field = fields[name]
        default_is_none = field.default is None
        default_factory_is_none = field.default_factory is None  # type: ignore[misc]
        annotation_includes_none = "None" in str(field.annotation)
        assert default_is_none or default_factory_is_none or annotation_includes_none, (
            f"section {name!r} is nullable-until-later and must accept None"
        )


def test_packet_blast_radius_uses_classification_model() -> None:
    """Batch B replaces the untyped placeholder with the classifier result."""
    packet_mod = import_module("mergecraft.evidence.packet")
    annotation = packet_mod.MergeEvidencePacket.model_fields["blast_radius"].annotation
    assert "BlastRadiusClassification" in str(annotation)


def test_packet_agent_section_carries_id_version_and_model() -> None:
    """The ``agent`` section must record id, version, and model."""
    packet_mod = import_module("mergecraft.evidence.packet")
    agent_cls = packet_mod.AgentMetadata
    fields = agent_cls.model_fields
    for name in ("id", "version", "model"):
        assert name in fields, f"agent.{name!r} missing from packet"


def test_packet_decision_section_exists() -> None:
    """A ``decision`` section is required even when the verdict is to block."""
    packet_mod = import_module("mergecraft.evidence.packet")
    fields = packet_mod.MergeEvidencePacket.model_fields
    assert "decision" in fields
