"""TH1 RED — behavioural contracts for ``select_rule_id`` (D4, TH3).

Lane A replaced ``_is_schema_failure`` with the ``_RULE_PREDICATES`` table plus a
catch-all ``return "schema_failure"`` at ``gates.py:451``. These tests pin direct
behaviour — no ``inspect.getsource`` structural assertions (TH3 deletes those).
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES, NAMED_GATE_POLICY_ROWS
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
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


def _schema_failure_packet() -> MergeEvidencePacket:
    return _packet()


def _changed_unread_packet() -> MergeEvidencePacket:
    finding = make_finding(
        tool="trajectory",
        rule_id="changed-unread-file",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="src/x.py was modified but never read during this run",
        path="src/x.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    return _packet(findings=[finding])


def _has_blockers_packet() -> MergeEvidencePacket:
    finding = make_finding(
        tool="agent",
        rule_id="SEC-1",
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
    return _packet(findings=[finding])


def _low_risk_passing_packet() -> MergeEvidencePacket:
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    classification = BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="No elevated blast-radius category was detected.",
        next_action="Eligible for automatic merge after required checks pass.",
        categories=[],
    )
    return _packet(findings=[], blast_radius=classification)


def _tool_loop_packet() -> MergeEvidencePacket:
    finding = make_finding(
        tool="trajectory",
        rule_id="repeated-tool-loop",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="the same call was repeated 5 times with identical arguments",
        path="",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    return _packet(findings=[finding])


def _high_risk_migration_packet() -> MergeEvidencePacket:
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    classification = BlastRadiusClassification(
        lane="high",
        auto_merge_lane="forbidden",
        reason="Detected blast-radius categories: migrations.",
        next_action="Require human review; automatic merge is forbidden.",
        categories=["migrations"],
    )
    return _packet(
        files_changed=["db/migrations/0007_drop_users.sql"],
        blast_radius=classification,
    )


_RULE_PACKET_BUILDERS: dict[str, Any] = {
    "high_risk_migration": _high_risk_migration_packet,
    "low_risk_passing": _low_risk_passing_packet,
    "has_blockers": _has_blockers_packet,
    "changed-unread-file": _changed_unread_packet,
    "tool_loop": _tool_loop_packet,
}


def test_catch_all_returns_schema_failure() -> None:
    """A packet matching no ``_RULE_PREDICATES`` row falls through to ``schema_failure``."""
    from mergecraft.agents.gates import select_rule_id

    assert select_rule_id(_schema_failure_packet()) == "schema_failure"


@pytest.mark.parametrize("rule_id", [rule_id for rule_id, _action in NAMED_GATE_POLICY_ROWS])
def test_each_rule_predicate_has_a_behavioural_case(rule_id: str) -> None:
    """One hand-built packet per named rule id; ``select_rule_id`` must return it."""
    from mergecraft.agents.gates import select_rule_id

    builder = _RULE_PACKET_BUILDERS[rule_id]
    packet = builder()
    assert select_rule_id(packet) == rule_id


def test_self_assessment_only_neutral_verdict_and_no_auto_merge_action() -> None:
    """Self-assessment-only packets: ``neutral`` verdict and gate action ≠ ``auto_merge`` (#41)."""
    from mergecraft.agents.gates import decide_action, decide_approval

    packet = _packet(
        self_assessment={"approved": True, "sha": "0123456789abcdef0123456789abcdef01234567"},
        findings=[],
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"
    action = decide_action(packet, policy=DEFAULT_GATE_POLICIES)
    assert str(action) != "auto_merge"


def test_has_blockers_outranks_changed_unread_file() -> None:
    """Behavioural replacement for ``test_gate_actions`` source-inspection (D4)."""
    from mergecraft.agents.gates import decide_action, select_rule_id

    blocker = make_finding(
        tool="agent",
        rule_id="SEC-1",
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
    unread = make_finding(
        tool="trajectory",
        rule_id="changed-unread-file",
        category="Maintainability & Code Quality",
        severity="Minor",
        confidence="certain",
        message="src/x.py was modified but never read",
        path="src/x.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )
    packet = _packet(findings=[unread, blocker])
    assert select_rule_id(packet) == "has_blockers"
    action = decide_action(packet, policy=DEFAULT_GATE_POLICIES)
    assert str(action) == "request_changes"
