"""TH1 RED — behavioural contracts for ``select_rule_id`` (D4, TH3).

Lane A replaced ``_is_schema_failure`` with the ``_RULE_PREDICATES`` table plus a
catch-all ``return "schema_failure"`` at ``gates.py:451``. These tests pin direct
behaviour — no ``inspect.getsource`` structural assertions (TH3 deletes those).
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.analyzers.finding import make_finding
from mergecraft.evidence.gate_policy import (
    DEFAULT_GATE_POLICIES,
    NAMED_GATE_POLICY_ROWS,
    GateAction,
)
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
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
    from mergecraft.classify.blast_radius import BlastRadiusClassification
    from mergecraft.evidence.packet import Decision

    classification = BlastRadiusClassification(
        lane="low",
        auto_merge_lane="eligible",
        reason="No elevated blast-radius category was detected.",
        next_action="Eligible for automatic merge after required checks pass.",
        categories=[],
    )
    packet = _packet(findings=[], blast_radius=classification)
    decision = Decision(
        verdict="success",
        reason="low-risk passing: trusted structural success with no blockers",
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet.model_copy(update={"decision": decision})


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


def _trusted_success_decision() -> Any:
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
    from mergecraft.evidence.packet import Decision

    return Decision(
        verdict="success",
        reason="success: review attested by terminal verdict and read coverage; no findings",
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )


def _clean_pass_packet() -> MergeEvidencePacket:
    """A clean, attested packet on a non-low lane — the #1076 misrouting case."""
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    classification = BlastRadiusClassification(
        lane="medium",
        auto_merge_lane="assisted",
        reason="Detected blast-radius categories: dependency_changes.",
        next_action="Use assisted review and verify the affected behavior.",
        categories=["dependency_changes"],
    )
    return _packet(blast_radius=classification, decision=_trusted_success_decision())


def _needs_human_review_packet() -> MergeEvidencePacket:
    """A structurally complete packet (decision row present) that matches no rule."""
    from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
    from mergecraft.evidence.packet import Decision

    return _packet(
        decision=Decision(
            verdict="neutral",
            reason="neutral: no typed findings to attest to the review",
            decided_by=TRUSTED_PACKET_DECIDED_BY,
        )
    )


_RULE_PACKET_BUILDERS: dict[str, Any] = {
    "high_risk_migration": _high_risk_migration_packet,
    "low_risk_passing": _low_risk_passing_packet,
    "has_blockers": _has_blockers_packet,
    "changed-unread-file": _changed_unread_packet,
    "tool_loop": _tool_loop_packet,
    "clean_pass": _clean_pass_packet,
    "needs_human_review": _needs_human_review_packet,
}


def test_catch_all_returns_schema_failure() -> None:
    """A structurally absent packet (no decision/findings/blast radius/trajectory)
    falls through to ``schema_failure`` — after the #1076 re-scope that is the
    *only* shape the catch-all may fire on."""
    from mergecraft.agents.gates import select_rule_id

    assert select_rule_id(_schema_failure_packet()) == "schema_failure"


def test_complete_packet_never_reads_schema_failure() -> None:
    """#1076: a parsed, validated packet that matches no specific rule routes to
    ``needs_human_review`` — the label never claims a schema failure on
    complete evidence."""
    from mergecraft.agents.gates import decide_action, select_rule_id

    packet = _needs_human_review_packet()
    assert select_rule_id(packet) == "needs_human_review"
    assert select_rule_id(packet) != "schema_failure"
    assert decide_action(packet, policy=DEFAULT_GATE_POLICIES) is GateAction.REQUIRE_HUMAN_REVIEW


def test_clean_pass_covers_auto_merge_eligible_lanes() -> None:
    """#1076: ``clean_pass`` is the lane-independent sibling of ``low_risk_passing``
    — a clean attested packet on a ``medium`` lane merges too."""
    from mergecraft.agents.gates import decide_action, select_rule_id
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    packet = _packet(
        blast_radius=BlastRadiusClassification(
            lane="medium",
            auto_merge_lane="assisted",
            reason="Detected blast-radius categories: dependency_changes.",
            next_action="Use assisted review and verify the affected behavior.",
            categories=["dependency_changes"],
        ),
        decision=_trusted_success_decision(),
    )
    assert select_rule_id(packet) == "clean_pass"
    assert decide_action(packet, policy=DEFAULT_GATE_POLICIES) is GateAction.AUTO_MERGE


def test_clean_pass_never_merges_a_forbidden_or_unknown_lane() -> None:
    """The blast-radius lane's own veto is respected: a ``forbidden`` (high) lane
    and a missing classification (unknown lane — #1056) escalate to a human
    instead of merging, even with a trusted success verdict."""
    from mergecraft.agents.gates import decide_action, select_rule_id
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    forbidden = _packet(
        blast_radius=BlastRadiusClassification(
            lane="high",
            auto_merge_lane="forbidden",
            reason="Detected blast-radius categories: auth_security_payment.",
            next_action="Require human review; automatic merge is forbidden.",
            categories=["auth_security_payment"],
        ),
        decision=_trusted_success_decision(),
    )
    assert select_rule_id(forbidden) == "needs_human_review"
    assert decide_action(forbidden, policy=DEFAULT_GATE_POLICIES) is (
        GateAction.REQUIRE_HUMAN_REVIEW
    )

    unclassified = _packet(decision=_trusted_success_decision())
    assert select_rule_id(unclassified) == "needs_human_review"
    assert decide_action(unclassified, policy=DEFAULT_GATE_POLICIES) is (
        GateAction.REQUIRE_HUMAN_REVIEW
    )


def test_clean_pass_yields_to_the_finding_and_migration_rules() -> None:
    """``clean_pass`` is ordered last of the specific rules: ``has_blockers``,
    ``changed-unread-file``, ``tool_loop`` and ``high_risk_migration`` keep
    winning when their signals coexist with a trusted success verdict."""
    from mergecraft.agents.gates import select_rule_id
    from mergecraft.classify.blast_radius import BlastRadiusClassification

    decided = _trusted_success_decision()
    assert select_rule_id(_has_blockers_packet().model_copy(update={"decision": decided})) == (
        "has_blockers"
    )
    assert select_rule_id(_changed_unread_packet().model_copy(update={"decision": decided})) == (
        "changed-unread-file"
    )
    assert select_rule_id(_tool_loop_packet().model_copy(update={"decision": decided})) == (
        "tool_loop"
    )
    migration = BlastRadiusClassification(
        lane="high",
        auto_merge_lane="forbidden",
        reason="Detected blast-radius categories: migrations.",
        next_action="Require human review; automatic merge is forbidden.",
        categories=["migrations"],
    )
    assert (
        select_rule_id(_packet(blast_radius=migration, decision=decided)) == "high_risk_migration"
    )


@pytest.mark.parametrize("rule_id", [rule_id for rule_id, _action in NAMED_GATE_POLICY_ROWS])
def test_each_rule_predicate_has_a_behavioural_case(rule_id: str) -> None:
    """One hand-built packet per named rule id; ``select_rule_id`` must return it."""
    from mergecraft.agents.gates import select_rule_id

    assert rule_id in _RULE_PACKET_BUILDERS, (
        f"missing behavioural packet builder for rule_id {rule_id!r} — "
        f"add a case to _RULE_PACKET_BUILDERS (known: {sorted(_RULE_PACKET_BUILDERS)})"
    )
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
    attached = packet.model_copy(update={"decision": decision})
    action = decide_action(attached, policy=DEFAULT_GATE_POLICIES)
    assert action != GateAction.AUTO_MERGE


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
    assert action == GateAction.REQUEST_CHANGES
