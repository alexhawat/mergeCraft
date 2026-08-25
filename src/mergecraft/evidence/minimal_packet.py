"""Minimal evidence-packet stubs for findings without on-disk packets."""

from __future__ import annotations

from typing import Any


def minimal_evidence_packet(fingerprint: str) -> dict[str, Any]:
    """Return the default unverified stub keyed by ``finding_id``."""
    return {
        "finding_id": fingerprint,
        "state": "unverified",
        "kinds": [],
    }


__all__ = ["minimal_evidence_packet"]
