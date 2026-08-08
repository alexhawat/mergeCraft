"""Merge Evidence Packet — schema derivation and version pinning (WA-T.1, WA-T.3).

Pin the contract that the packet's JSON Schema must come from the Pydantic
models (mirroring ``mergecraft.analyzers.finding.findings_output_schema`` at
``src/mergecraft/analyzers/finding.py:138``) and that the version is asserted
(D7).
"""

from __future__ import annotations

import json

from tests.analyzers.support import import_module as import_finding_module
from tests.evidence.support import import_module


def test_evidence_packet_schema_is_derived_not_handwritten() -> None:
    """The packet's JSON Schema must be derived from the Pydantic models (D3)."""
    finding_mod = import_finding_module("mergecraft.analyzers.finding")
    packet_mod = import_module("mergecraft.evidence.packet")

    schema = packet_mod.packet_output_schema()
    assert isinstance(schema, dict)
    assert schema.get("type") == "object"

    properties = schema.get("properties")
    assert isinstance(properties, dict)

    # ``findings`` must reuse ``Finding.model_json_schema()`` — never a hand-written
    # parallel schema (D3 + the precedent at analyzers/finding.py:138).
    findings_prop = properties.get("findings")
    assert isinstance(findings_prop, dict)
    assert findings_prop.get("type") == "array"
    items = findings_prop.get("items")
    assert isinstance(items, dict)

    finding_schema = finding_mod.Finding.model_json_schema()
    assert items == finding_schema or items.get("properties") == finding_schema.get("properties")


def test_packet_findings_match_finding_model_json_schema() -> None:
    """Each ``findings`` item must match ``Finding.model_json_schema()`` (D3)."""
    finding_mod = import_finding_module("mergecraft.analyzers.finding")
    packet_mod = import_module("mergecraft.evidence.packet")

    packet_cls = packet_mod.MergeEvidencePacket
    fields = packet_cls.model_fields
    assert "findings" in fields
    findings_field = fields["findings"]
    # The annotation should reference the same ``Finding`` Pydantic model.
    annotation = getattr(findings_field, "annotation", None)
    assert annotation is not None
    origin = getattr(annotation, "__origin__", None)
    args = getattr(annotation, "__args__", ())
    assert origin is list
    assert finding_mod.Finding in args


def test_evidence_packet_requires_schema_version() -> None:
    """``schema_version`` is a required top-level field (D7)."""
    packet_mod = import_module("mergecraft.evidence.packet")
    fields = packet_mod.MergeEvidencePacket.model_fields
    assert "schema_version" in fields
    # ``is_required`` is True when no default is supplied.
    assert fields["schema_version"].is_required() is True


def test_packet_schema_version_is_pinned() -> None:
    """The current schema version is a literal the suite pins (D7).

    Any field-level change to the packet (additive or otherwise) that is not
    accompanied by a version bump must cause this assertion to fail, so the
    reviewer catches silent schema drift at the gate.
    """
    packet_mod = import_module("mergecraft.evidence.packet")

    # The packet must publish a single source of truth for the current version.
    assert hasattr(packet_mod, "PACKET_SCHEMA_VERSION")
    pinned = packet_mod.PACKET_SCHEMA_VERSION
    assert isinstance(pinned, str)
    assert pinned.count(".") == 2  # major.minor.patch

    # And the same literal must appear in the model field default.
    fields = packet_mod.MergeEvidencePacket.model_fields
    assert fields["schema_version"].default == pinned


def test_packet_schema_round_trip_json_serializes() -> None:
    """The derived schema must validate the serialized form of a real packet."""
    packet_mod = import_module("mergecraft.evidence.packet")

    packet = packet_mod.MergeEvidencePacket(**_packet_kwargs())
    serialized = packet.model_dump_json()
    reparsed = packet_mod.MergeEvidencePacket.model_validate_json(serialized)
    assert reparsed == packet
    # The serialized form must be valid JSON.
    json.loads(serialized)


def _packet_kwargs() -> dict[str, object]:
    from tests.evidence.support import sample_minimal_packet_dict

    return sample_minimal_packet_dict()
