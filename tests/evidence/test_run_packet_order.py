"""RED — build_run_packet decision ordering (AG3 / MCB-15)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.gate_policy import GateAction
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    MergeEvidencePacket,
)

if TYPE_CHECKING:
    from pathlib import Path


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


def test_decide_action_sees_the_attached_decision(tmp_path: Path) -> None:
    from mergecraft.agents.gates import decide_action, decide_approval
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES

    blocker = make_finding(
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
    packet = _packet(findings=[blocker])
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    attached = packet.model_copy(update={"decision": decision})

    # If decide_action ran before attach, low_risk/null decision could skew the action.
    action_before_order_fix = decide_action(packet, policy=DEFAULT_GATE_POLICIES)
    action_after_attach = decide_action(attached, policy=DEFAULT_GATE_POLICIES)
    assert action_after_attach == GateAction.REQUEST_CHANGES
    assert action_before_order_fix == action_after_attach
