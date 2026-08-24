"""Pins for shared finding-id lookup helpers (#453)."""

from __future__ import annotations

from mergecraft.review.finding_lookup import lookup_packet_by_finding_id


def test_lookup_packet_by_finding_id_matches_nested_finding_id_field() -> None:
    """Happy — lookup falls back to packet ``finding_id`` when stem keys differ."""
    nested_id = "legacy-finding-alias-001"
    packets = {
        "other-stem": {
            "finding_id": nested_id,
            "state": "unverified",
            "kinds": [],
        }
    }
    packet = lookup_packet_by_finding_id(nested_id, packets)
    assert packet is not None
    assert packet["finding_id"] == nested_id


def test_lookup_packet_by_finding_id_prefers_direct_fingerprint_key() -> None:
    """Happy — direct fingerprint stem wins over nested ``finding_id`` scan."""
    fingerprint = "bbbbbbbbbbbbbbbbbbbbbbbb"
    packets = {
        fingerprint: {"finding_id": fingerprint, "state": "proven", "kinds": ["test"]},
        "other": {"finding_id": fingerprint, "state": "unverified", "kinds": []},
    }
    packet = lookup_packet_by_finding_id(fingerprint, packets)
    assert packet is not None
    assert packet["state"] == "proven"


def test_lookup_packet_by_finding_id_resolves_nested_aggregate_fingerprint() -> None:
    """Happy — aggregate evidence packets expose per-finding rows under ``packets``."""
    fingerprint = "cccccccccccccccccccccccc"
    packets = {
        "merge-run": {
            "schema_version": "1.8.0",
            "packets": {
                fingerprint: {
                    "finding_id": fingerprint,
                    "state": "proven",
                    "kinds": ["analyzer_findings"],
                }
            },
        }
    }
    packet = lookup_packet_by_finding_id(fingerprint, packets)
    assert packet is not None
    assert packet["finding_id"] == fingerprint
    assert packet["state"] == "proven"
