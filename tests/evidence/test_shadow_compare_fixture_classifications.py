"""The shadow-compare fixture packets carry real reasons and a full checklist (#1056 part 2).

``evidence/shadow_compare.py`` hand-builds the blast-radius classifications for
its advisory replay. A hand-built classification without ``reasons`` or
``checklist`` reads as a pre-1.18.0 packet, so the replay would exercise the
legacy gate route instead of the current one.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.classify.blast_radius import GATE_ORDER
from mergecraft.evidence.shadow_compare import _runtime_packets

_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_ALWAYS_ON: tuple[str, ...] = (
    "inputs",
    "migrations",
    "auth_security_payment",
    "secrets_config_deployment",
    "irreversible_infra",
    "public_api",
    "dependencies",
    "tests",
    "review_config",
    "source",
)


def _classifications() -> list[Any]:
    return [packet.blast_radius for packet in _runtime_packets()]


def test_the_fixture_packets_carry_a_blast_radius() -> None:
    classifications = _classifications()

    assert len(classifications) >= 2
    assert all(item is not None for item in classifications)


@pytest.mark.parametrize("index", [0, 1], ids=["high-migration", "low-generated"])
def test_each_fixture_classification_has_reasons_and_a_full_checklist(index: int) -> None:
    classification = _classifications()[index]

    assert len(classification.reasons) >= 1
    names = [gate.gate for gate in classification.checklist]
    # Every always-on gate, in ``GATE_ORDER``; an optional-signal gate (``scope``) may
    # be absent when the fixture supplies no such signal.
    assert names == [gate for gate in GATE_ORDER if gate in names]
    assert names[: len(_ALWAYS_ON)] == list(_ALWAYS_ON)
    assert classification.lane == max(
        (reason.lane for reason in classification.reasons), key=_RANK.__getitem__
    )
    all_passed = all(gate.passed is True for gate in classification.checklist)
    assert (classification.auto_merge_lane == "eligible") is all_passed
