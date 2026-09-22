"""Merge Evidence Packet — round-trip and ``extra=\"forbid\"`` (WA-T.2)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from tests.evidence.support import import_module, sample_minimal_packet_dict

_CANARY_SECRET = "sk-canary-w0-8-do-not-leak-7f3a9b2c1d4e5f6a"


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


def test_packet_json_cannot_restore_trajectory_secrets() -> None:
    """Sanitized combined and nested external calls stay safe in the final packet."""
    from mergecraft.evidence.trajectory import (
        ExternalTraceRef,
        ToolCallRecord,
        build_trajectory_record,
    )
    from mergecraft.mcp.tool_state import init_tool_state

    state = init_tool_state(owner="acme", name="demo", dir="/tmp/demo")
    state.tool_calls.append(
        ToolCallRecord(
            sequence=1,
            tool="Read",
            signature="Read:state",
            intent="read",
            ok=True,
            command=f"cat {_CANARY_SECRET} src/state.py",
            error=f"state {_CANARY_SECRET}",
            paths=["src/state.py", f"src/{_CANARY_SECRET}.py"],
        )
    )
    external = ExternalTraceRef(
        source="mergecraft.tracing",
        event_count=1,
        tool_calls=[
            ToolCallRecord(
                sequence=2,
                tool="Read",
                signature="Read:external",
                intent="read",
                ok=True,
                command=f"cat {_CANARY_SECRET} src/external.py",
                error=f"external {_CANARY_SECRET}",
                paths=["src/external.py", f"src/{_CANARY_SECRET}.py"],
            )
        ],
    )
    trajectory = build_trajectory_record(state, external_trace=external)
    payload = sample_minimal_packet_dict()
    payload["trajectory"] = trajectory.model_dump(mode="json")

    packet = import_module("mergecraft.evidence.packet").MergeEvidencePacket(**payload)
    serialized = packet.model_dump_json()

    assert _CANARY_SECRET not in serialized
    assert serialized.count("src/external.py") >= 2
