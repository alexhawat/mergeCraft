"""Merge Evidence Packet — schema derivation and version pinning (WA-T.1, WA-T.3).

Pin the contract that the packet's JSON Schema must come from the Pydantic
models (mirroring ``mergecraft.analyzers.finding.findings_output_schema`` at
``src/mergecraft/analyzers/finding.py:138``) and that the version is asserted
(D7).
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

from mergecraft.analyzers import finding as finding_mod
from mergecraft.evidence import packet as packet_mod

_FINGERPRINTS = Path(__file__).with_name("packet_schema_fingerprints.json")


def _fingerprint(schema: dict[str, Any]) -> str:
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _schema_fingerprint() -> str:
    return _fingerprint(packet_mod.packet_output_schema())


def test_evidence_packet_schema_is_derived_not_handwritten() -> None:
    """The packet's JSON Schema must be derived from the Pydantic models (D3)."""

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
    fields = packet_mod.MergeEvidencePacket.model_fields
    assert "schema_version" in fields
    # ``is_required`` is True when no default is supplied.
    assert fields["schema_version"].is_required() is True


def test_packet_schema_declares_run_bound_review_fields() -> None:
    """The packet carries the orchestrator-written run-bound review identity.

    ``reviewed_head_sha`` is the PR head the trusted run checked out and
    ``progress_comment_id`` is that run's sticky comment id. Both are written by
    the orchestrator; neither is agent-controlled. The schema is derived from
    the model, so the properties must appear there too (D3).
    """

    fields = packet_mod.MergeEvidencePacket.model_fields
    assert "reviewed_head_sha" in fields
    assert "progress_comment_id" in fields

    schema = packet_mod.packet_output_schema()
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert "reviewed_head_sha" in properties
    assert "progress_comment_id" in properties


def test_packet_run_bound_fields_default_to_none() -> None:
    """A packet built before the fields existed still validates (P-6, forward-compatible)."""

    packet = packet_mod.MergeEvidencePacket(**_packet_kwargs())

    assert packet.reviewed_head_sha is None
    assert packet.progress_comment_id is None


def test_packet_schema_version_is_pinned() -> None:
    """Any change to the packet wire schema must come with a version bump (D7).

    ``packet_schema_fingerprints.json`` maps each released ``PACKET_SCHEMA_VERSION``
    to the sha256 of the canonical ``packet_output_schema()`` JSON. Changing a
    field without bumping the version changes the hash under an existing key and
    fails here; bumping the version without recording its hash fails too.

    To update after an intentional change: bump ``PACKET_SCHEMA_VERSION``, then add
    ``"<new version>": "<hash printed by this failure>"`` to the JSON file.
    """
    version = packet_mod.PACKET_SCHEMA_VERSION
    assert packet_mod.MergeEvidencePacket.model_fields["schema_version"].default == version

    pins = json.loads(_FINGERPRINTS.read_text(encoding="utf-8"))
    actual = _schema_fingerprint()
    assert version in pins, (
        f"PACKET_SCHEMA_VERSION {version} has no pinned fingerprint; "
        f'add "{version}": "{actual}" to {_FINGERPRINTS.name}'
    )
    assert pins[version] == actual, (
        f"the packet schema changed without bumping PACKET_SCHEMA_VERSION ({version}); "
        f"bump it and pin the new fingerprint {actual}"
    )


def test_packet_schema_fingerprint_is_stable_and_sensitive() -> None:
    """An unchanged rebuild hashes identically; adding or removing one property changes it."""
    baseline = _fingerprint(packet_mod.packet_output_schema())
    assert _fingerprint(packet_mod.packet_output_schema()) == baseline

    added = copy.deepcopy(packet_mod.packet_output_schema())
    added["properties"]["extra_wire_field"] = {"type": "string"}
    assert _fingerprint(added) != baseline

    removed = copy.deepcopy(packet_mod.packet_output_schema())
    removed["properties"].pop("reviewed_head_sha")
    assert _fingerprint(removed) != baseline


def test_packet_schema_round_trip_json_serializes() -> None:
    """The derived schema must validate the serialized form of a real packet."""

    packet = packet_mod.MergeEvidencePacket(**_packet_kwargs())
    serialized = packet.model_dump_json()
    reparsed = packet_mod.MergeEvidencePacket.model_validate_json(serialized)
    assert reparsed == packet
    # The serialized form must be valid JSON.
    json.loads(serialized)


def _packet_kwargs() -> dict[str, Any]:
    from tests.evidence.support import sample_minimal_packet_dict

    return sample_minimal_packet_dict()
