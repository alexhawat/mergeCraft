"""Merge Evidence Packet — round-trip and ``extra=\"forbid\"`` (WA-T.2)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from tests.evidence.support import import_module, sample_minimal_packet_dict


def test_evidence_packet_round_trips_through_json() -> None:
    """A fully populated packet serializes to JSON and re-validates with zero errors."""
    packet_mod = import_module("mergecraft.evidence.packet")

    payload = sample_minimal_packet_dict()
    packet = packet_mod.MergeEvidencePacket(**payload)
    serialized = packet.model_dump_json()
    reparsed = packet_mod.MergeEvidencePacket.model_validate_json(serialized)
    assert reparsed == packet

    # The serialized form must also be plain JSON.
    json.loads(serialized)


def test_evidence_packet_round_trips_through_dict() -> None:
    """A packet serializes to a dict and re-validates from the dict (no info loss)."""
    packet_mod = import_module("mergecraft.evidence.packet")

    payload = sample_minimal_packet_dict()
    packet = packet_mod.MergeEvidencePacket(**payload)
    dumped = packet.model_dump()
    reparsed = packet_mod.MergeEvidencePacket(**dumped)
    assert reparsed == packet


def test_evidence_packet_rejects_unknown_fields() -> None:
    """``extra=\"forbid\"`` rejects unknown fields (D3 — packet composes Finding strictly)."""
    packet_mod = import_module("mergecraft.evidence.packet")

    payload = sample_minimal_packet_dict()
    payload_with_extra: dict[str, Any] = {**payload, "rogue_field": "should be rejected"}
    with pytest.raises(ValidationError):
        packet_mod.MergeEvidencePacket(**payload_with_extra)


def test_evidence_packet_rejects_nested_unknown_fields() -> None:
    """``extra=\"forbid\"`` also applies to nested models (e.g. ``agent``)."""
    packet_mod = import_module("mergecraft.evidence.packet")

    payload = sample_minimal_packet_dict()
    nested = dict(payload["agent"])  # type: ignore[arg-type]
    nested["rogue_field"] = "should be rejected"
    payload_bad: dict[str, Any] = {**payload, "agent": nested}
    with pytest.raises(ValidationError):
        packet_mod.MergeEvidencePacket(**payload_bad)
