"""RED — gate fail-closed matrix (AG3 / MCB-15)."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.gate_policy import GateAction
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    Decision,
    MergeEvidencePacket,
)


def _packet(**overrides: Any) -> MergeEvidencePacket:
    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#42",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": [],
        "findings": [],
        "deterministic_checks": [],
        "self_assessment": None,
        "decision": None,
        "blast_radius": None,
        "trajectory": None,
        "evals": None,
    }
    base.update(overrides)
    return MergeEvidencePacket(**base)


def _low_blast_packet(**overrides: Any) -> MergeEvidencePacket:
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    blast = BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="low",
        next_action="eligible",
        categories=[],
    )
    return _packet(findings=[], blast_radius=blast, **overrides)


def _auto_merge_action(packet: MergeEvidencePacket) -> GateAction:
    from mergecraft.agents.gates import decide_action
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    return decide_action(packet, policy=DEFAULT_GATE_POLICIES)


@pytest.mark.parametrize(
    "case",
    [
        "run_succeeded_false",
        "untrusted_tier",
        "neutral_verdict",
        "missing_decision",
        "blocker_present",
        "evidence_unavailable",
    ],
)
def test_never_auto_merge(case: str) -> None:
    from mergecraft.agents.gates import decide_approval

    packet = _low_blast_packet()
    run_succeeded = True
    tier: str = "trusted"
    if case == "run_succeeded_false":
        run_succeeded = False
    elif case == "untrusted_tier":
        tier = "untrusted"
    elif case == "neutral_verdict":
        packet = _packet(
            findings=[
                make_finding(
                    tool="ruff",
                    rule_id="F401",
                    category="Maintainability & Code Quality",
                    severity="Minor",
                    confidence="likely",
                    message="unused",
                    path="src/x.py",
                    start_line=1,
                    end_line=1,
                    source="analyzer",
                )
            ],
            blast_radius=_low_blast_packet().blast_radius,
        )
    elif case == "missing_decision":
        packet = _low_blast_packet(decision=None)
    elif case == "blocker_present":
        packet = _packet(
            findings=[
                make_finding(
                    tool="agent",
                    rule_id="SEC",
                    category="Security & Privacy",
                    severity="Critical",
                    confidence="certain",
                    message="blocker",
                    path="src/auth.py",
                    start_line=1,
                    end_line=1,
                    source="agent",
                    introduced_by_pr="true",
                )
            ],
            blast_radius=_low_blast_packet().blast_radius,
        )
    elif case == "evidence_unavailable":
        packet = _low_blast_packet(
            deterministic_checks=[{"name": "ci", "status": "unavailable", "command": "make ci"}]
        )

    decision = decide_approval(packet, run_succeeded=run_succeeded, tier=tier)
    packet_with_decision = packet.model_copy(update={"decision": decision})
    action = _auto_merge_action(packet_with_decision)
    assert action != GateAction.AUTO_MERGE


def test_low_risk_passing_requires_an_explicit_positive_decision() -> None:
    from mergecraft.agents.gates import _is_low_risk_passing

    neutral = Decision(
        verdict="neutral",
        reason="no findings",
        decided_by="mergecraft.agents.gates.decide_approval",
    )
    packet = _low_blast_packet(decision=neutral)
    assert not _is_low_risk_passing(packet)


def test_low_risk_passing_actually_checks_run_succeeded() -> None:
    from mergecraft.agents.gates import _is_low_risk_passing, decide_action, decide_approval
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    packet = _low_blast_packet()
    decision = decide_approval(packet, run_succeeded=False, tier="trusted")
    packet_with = packet.model_copy(update={"decision": decision})
    assert decide_action(packet_with, policy=DEFAULT_GATE_POLICIES) != GateAction.AUTO_MERGE
    assert not _is_low_risk_passing(packet_with)
