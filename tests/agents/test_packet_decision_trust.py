"""GREEN — packet decision trust (AG3 / LR-1)."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.analyzers.finding import make_finding
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


def test_untrusted_decided_by_is_refused() -> None:
    from mergecraft.agents.gates import decide_approval

    forged = Decision(
        verdict="success",
        reason="model said ok",
        decided_by="untrusted.agent",
    )
    packet = _packet(decision=forged)
    with pytest.raises(ValueError, match=r"decided_by|trusted"):
        decide_approval(packet, run_succeeded=True, tier="trusted")


def test_success_verdict_with_a_critical_finding_is_refused() -> None:
    from mergecraft.agents.gates import decide_approval

    forged = Decision(
        verdict="success",
        reason="forged",
        decided_by="mergecraft.agents.gates.decide_approval",
    )
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
    packet = _packet(findings=[blocker], decision=forged)
    with pytest.raises(ValueError, match=r"blocker|failure"):
        decide_approval(packet, run_succeeded=True, tier="trusted")


def test_decide_approval_tags_trusted_packet_decided_by() -> None:
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY, decide_approval

    finding = make_finding(
        tool="ruff",
        rule_id="F401",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="likely",
        message="finding",
        path="src/x.py",
        start_line=1,
        end_line=1,
        source="analyzer",
    )
    packet = _packet(findings=[finding])
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.decided_by == TRUSTED_PACKET_DECIDED_BY


_AUTO_MERGE_CASES: tuple[tuple[str, bool, str], ...] = (
    ("trusted_explicit_success", True, "trusted"),
    ("trusted_neutral_empty_findings", False, "trusted"),
    ("untrusted_never", False, "untrusted"),
    ("failed_run", False, "trusted"),
)


@pytest.mark.parametrize(("label", "should_merge", "tier"), _AUTO_MERGE_CASES)
def test_hypothesis_auto_merge_implies_positive_decision(
    label: str,
    should_merge: bool,
    tier: str,
) -> None:
    from mergecraft.agents.gates import decide_action, decide_approval
    from mergecraft.classify.blast_radius import BlastRadiusClassification
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES, GateAction

    blast = BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="low",
        next_action="eligible",
        categories=[],
    )
    packet = _packet(findings=[], blast_radius=blast)
    run_ok = label != "failed_run"
    if label == "trusted_explicit_success":
        from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY

        decision = Decision(
            verdict="success",
            reason="explicit trusted success for low-risk passing predicate",
            decided_by=TRUSTED_PACKET_DECIDED_BY,
        )
    else:
        decision = decide_approval(packet, run_succeeded=run_ok, tier=tier)
    attached = packet.model_copy(update={"decision": decision})
    action = decide_action(attached, policy=DEFAULT_GATE_POLICIES)
    if should_merge:
        assert action == GateAction.AUTO_MERGE
        assert attached.decision is not None
        assert attached.decision.verdict == "success"
    else:
        assert action != GateAction.AUTO_MERGE
