"""Pytest fixtures for merge-evidence packet tests (WA-T)."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_packet() -> dict[str, object]:
    """A round-trippable packet payload for the WA-T RED suite."""
    from tests.evidence.support import sample_minimal_packet_dict

    return sample_minimal_packet_dict()
