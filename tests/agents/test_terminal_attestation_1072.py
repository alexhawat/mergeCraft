"""#1072 — terminal verdict + read coverage attest a clean zero-finding review.

On PR #1068 (run 40670533851, a 161-line lockfile-only bump) the reviewing
agent ran a thorough clean review and submitted terminal ``approve`` with
zero typed findings. The structural gate answered ``neutral — no typed
findings to attest to the review``; the fallback guard read that as "no
verdict" and reran the whole review on the next provider at 398,912 input
tokens. A clean review's correct result *is* an empty findings list, so the
non-empty-list attestation can never vouch for it — the packet-overload gate
now accepts the MCP-recorded terminal ``approve`` plus observed
``trajectory.read_coverage`` as attestation instead.

Pinned contract:

- trusted + run succeeded + no blockers + terminal ``approve`` + observed
  read coverage + zero findings -> ``success``, with the reason naming the
  attestation.
- the same signals under tier ``untrusted`` or a failed run stay
  ``neutral`` (D14 inertness / failed-run honesty — attestation never
  widens).
- unknown read coverage, a missing trajectory, or a missing terminal
  verdict stay ``neutral`` (unknown is never green, #1056).
- the one-way ratchet (#619) still binds ``request_changes`` downward, and
  a typed blocker still wins outright over terminal attestation.
- ``self_assessment`` stays advisory-only: never an attestation input and
  never the reason's named basis.
- the legacy list-only overload keeps its old behaviour — an empty list is
  ``neutral`` regardless, because no attestation metadata is available.
"""

from __future__ import annotations

from typing import Any

from mergecraft.agents.gates import decide_approval
from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    MergeEvidencePacket,
    SelfAssessment,
)
from mergecraft.evidence.trajectory import TrajectoryRecord

EXPECTED_REASON = "success: review attested by terminal verdict and read coverage; no findings"


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


def _attested_clean_packet(**overrides: Any) -> MergeEvidencePacket:
    """The PR #1068 attempt-1 shape: terminal approve, observed reads, zero findings."""
    base: dict[str, Any] = {
        "findings": [],
        "agent_terminal_verdict": "approve",
        "trajectory": TrajectoryRecord(read_coverage=True),
    }
    base.update(overrides)
    return _packet(**base)


def _blocker() -> Finding:
    return make_finding(
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


def test_terminal_approve_with_read_coverage_attests_clean_review() -> None:
    """The #1072 core case: attested clean review decides ``success`` with no findings."""
    packet = _attested_clean_packet()
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"
    assert decision.reason == EXPECTED_REASON


def test_untrusted_tier_stays_inert_despite_terminal_attestation() -> None:
    """D14: attestation never widens an untrusted-tier run to ``success``."""
    packet = _attested_clean_packet()
    decision = decide_approval(packet, run_succeeded=True, tier="untrusted")
    assert decision.verdict == "neutral"
    assert "untrusted tier" in decision.reason, (
        "the reason is the fallback chain's only signal that a retry cannot help (#1078)"
    )


def test_failed_run_stays_neutral_despite_terminal_attestation() -> None:
    """A crashed / timed-out run must not propagate a permissive outcome (D13)."""
    packet = _attested_clean_packet()
    decision = decide_approval(packet, run_succeeded=False, tier="trusted")
    assert decision.verdict == "neutral"
    assert "review attested by terminal verdict" not in decision.reason, (
        "a refused attestation must not be named as the reason for the neutral verdict"
    )


def test_unknown_read_coverage_stays_neutral() -> None:
    """No observed read is *unknown*, not zero — unknown is never green (#1056)."""
    packet = _attested_clean_packet(trajectory=TrajectoryRecord(read_coverage=False))
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"
    assert decision.reason == "neutral: no typed findings to attest to the review"


def test_missing_trajectory_stays_neutral() -> None:
    """No trajectory record at all carries no read evidence."""
    packet = _attested_clean_packet(trajectory=None)
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"
    assert decision.reason == "neutral: no typed findings to attest to the review"


def test_missing_terminal_verdict_stays_neutral() -> None:
    """Read coverage without a terminal ``approve`` does not attest the review."""
    packet = _attested_clean_packet(agent_terminal_verdict=None)
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"
    assert decision.reason == "neutral: no typed findings to attest to the review"


def test_blocker_still_wins_over_terminal_attestation() -> None:
    """A typed blocker outvotes terminal attestation — the decision stays monotone."""
    packet = _attested_clean_packet(findings=[_blocker()])
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "failure"


def test_request_changes_ratchet_unchanged_with_read_coverage() -> None:
    """#619: ``request_changes`` still binds downward; attestation never applies to it."""
    packet = _attested_clean_packet(agent_terminal_verdict="request_changes")
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"
    assert decision.reason == (
        "neutral: agent terminal verdict request_changes; no structural blocker attested"
    )


def test_self_assessment_is_never_an_attestation_input() -> None:
    """An approving self-assessment with read coverage but no terminal verdict: neutral."""
    packet = _packet(
        self_assessment=SelfAssessment(
            approved=True, sha="0123456789abcdef0123456789abcdef01234567"
        ),
        trajectory=TrajectoryRecord(read_coverage=True),
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "neutral"


def test_self_assessment_is_not_named_as_the_attestation_basis() -> None:
    """When both rows are present, the reason names the terminal attestation — the
    advisory self-assessment is never cited as the basis for the verdict (#41)."""
    packet = _attested_clean_packet(
        self_assessment=SelfAssessment(
            approved=True, sha="0123456789abcdef0123456789abcdef01234567"
        )
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"
    assert decision.reason == EXPECTED_REASON
    assert "self_assessment" not in decision.reason


def test_legacy_list_overload_keeps_empty_list_neutral() -> None:
    """The list-only overload has no attestation metadata: empty stays ``neutral``."""
    assert decide_approval([], run_succeeded=True, tier="trusted") == "neutral"


def test_attested_clean_review_routes_clean_pass_not_schema_failure() -> None:
    """The #1068 scenario end to end: attested clean review on a medium lane yields
    ``success`` and routes to ``clean_pass`` -> ``auto_merge``, never the
    ``schema_failure`` catch-all (#1072 + #1076)."""
    from mergecraft.agents.gates import decide_action, select_rule_id
    from mergecraft.classify.blast_radius import BlastRadiusClassification
    from mergecraft.evidence.gate_policy import DEFAULT_GATE_POLICIES, GateAction

    packet = _attested_clean_packet(
        blast_radius=BlastRadiusClassification(
            lane="medium",
            auto_merge_lane="assisted",
            reason="Detected blast-radius categories: dependency_changes.",
            next_action="Use assisted review and verify the affected behavior.",
            categories=["dependency_changes"],
        )
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"
    decided = packet.model_copy(update={"decision": decision})
    assert select_rule_id(decided) == "clean_pass"
    assert decide_action(decided, policy=DEFAULT_GATE_POLICIES) is GateAction.AUTO_MERGE


def test_self_published_clean_review_decides_success() -> None:
    """The wave-0 + wave-1 contract (#1074 + #1072), asserted together.

    A compliant self-published review renders its packet *inside* the terminal
    ``create_pull_request_review`` call, so the trajectory audit runs with
    ``in_flight_tool`` naming that call and — post-#1074 — produces **no**
    ``missing-completion-signal`` run-health row. The resulting packet has
    zero typed findings and zero run-health rows; the gate's terminal
    attestation (#1072) is what lets it decide ``success`` rather than
    ``neutral`` and trigger a full fallback re-review. Pin the composition,
    not just the absence of the old false-positive row.
    """
    from mergecraft.evidence.packet import RunHealth
    from mergecraft.evidence.trajectory import ToolCallRecord
    from mergecraft.evidence.trajectory_audit import audit_trajectory

    record = TrajectoryRecord(
        tool_calls=[
            ToolCallRecord(
                sequence=1,
                tool="read_file",
                signature="read_file:diff",
                intent="read",
                ok=True,
                paths=["uv.lock"],
            ),
            ToolCallRecord(
                sequence=2,
                tool="run_static_checks",
                signature="run_static_checks:all",
                intent="verify",
                ok=True,
                outcome_ok=True,
            ),
        ],
        files_read=["uv.lock"],
        read_coverage=True,
    )
    run_findings = audit_trajectory(record, in_flight_tool="create_pull_request_review")
    assert run_findings == [], (
        "a clean self-published record must produce no run-health rows — "
        f"got {[f.rule_id for f in run_findings]}"
    )

    packet = _attested_clean_packet(
        trajectory=record,
        run_health=RunHealth(findings=run_findings, conclusion="clean"),
    )
    decision = decide_approval(packet, run_succeeded=True, tier="trusted")
    assert decision.verdict == "success"
    assert decision.reason == EXPECTED_REASON
