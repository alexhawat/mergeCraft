"""Decision-contract tests for ``agents/gates.py`` aimed at mutation survivors (W3.3-3).

The nightly mutation lane reported 9 of 12 sampled mutants surviving in
``agents/gates.py``. Each test here pins one behaviour the existing suites left
unasserted, through the public ``decide_approval`` / ``select_rule_id`` /
``subagent_denied_tool_names`` entry points.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest
from tests.agents.test_harness_render import _tool_ctx

from mergecraft.agents import gates
from mergecraft.agents.gates import (
    TERMINAL_PROTOCOL_DENIED_TOOL_NAMES,
    TRUSTED_PACKET_DECIDED_BY,
    decide_approval,
    select_rule_id,
    subagent_denied_tool_names,
)
from mergecraft.analyzers.finding import make_finding
from mergecraft.classify.blast_radius import GATE_ORDER, BlastRadiusClassification, ChecklistGate
from mergecraft.evidence.packet import (
    PACKET_SCHEMA_VERSION,
    AgentMetadata,
    Decision,
    MergeEvidencePacket,
)

if TYPE_CHECKING:
    from pathlib import Path


def _packet(**overrides: Any) -> MergeEvidencePacket:
    base: dict[str, Any] = {
        "schema_version": PACKET_SCHEMA_VERSION,
        "change_id": "acme/demo#42",
        "agent": AgentMetadata(id="claude", version="0.0.0", model="claude-sonnet-4-5"),
        "files_changed": ["src/x.py"],
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


def _finding(severity: str) -> Any:
    return make_finding(
        tool="trajectory",
        rule_id="changed-unread-file",
        category="Maintainability & Code Quality",
        severity=severity,
        confidence="certain",
        message="src/x.py was modified but never read during this run",
        path="src/x.py",
        start_line=1,
        end_line=1,
        source="agent",
        introduced_by_pr="true",
    )


def _blast(
    lane: str,
    gate_values: dict[str, bool | None] | None,
    *,
    auto_merge_lane: str = "eligible",
) -> BlastRadiusClassification:
    """A classification whose checklist lists every gate; ``gate_values`` overrides ``True``."""
    checklist: list[ChecklistGate] = []
    if gate_values is not None:
        checklist = [ChecklistGate(gate=g, passed=gate_values.get(g, True)) for g in GATE_ORDER]
    return BlastRadiusClassification(
        lane=lane,  # type: ignore[arg-type]
        auto_merge_lane=auto_merge_lane,  # type: ignore[arg-type]
        reason="fixture",
        next_action="fixture",
        categories=[],
        checklist=checklist,
    )


def _trusted_success(packet: MergeEvidencePacket) -> MergeEvidencePacket:
    decision = Decision(
        verdict="success",
        reason="fixture",
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet.model_copy(update={"decision": decision})


# -- deny list ------------------------------------------------------------------------


def test_subagent_deny_list_always_carries_the_terminal_protocol_tools(tmp_path: Path) -> None:
    denied = subagent_denied_tool_names(_tool_ctx(tmp_path))
    assert set(TERMINAL_PROTOCOL_DENIED_TOOL_NAMES) <= set(denied)
    assert len(denied) == len(set(denied)), "the union must not duplicate a derived name"


def test_deny_list_is_the_complement_of_the_admitted_surface(tmp_path: Path) -> None:
    denied = set(subagent_denied_tool_names(_tool_ctx(tmp_path)))
    # Read-only reviewer tools stay available; mutating ones are denied.
    assert "report_progress" in denied
    assert "checkout_pr" not in denied
    assert "read_file" not in denied


def test_an_empty_derived_deny_list_refuses_to_start(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gates, "build_orchestrator_tools", lambda _ctx, _schema=None: [])
    with pytest.raises(RuntimeError, match="deny list derived empty"):
        subagent_denied_tool_names(_tool_ctx(tmp_path))


# -- decision reason ------------------------------------------------------------------


def test_untrusted_tier_neutral_names_the_inert_attestation() -> None:
    packet = _packet(findings=[_finding("Minor")])
    decision = decide_approval(packet, run_succeeded=True, tier="untrusted")
    assert decision.verdict == "neutral"
    assert decision.reason.startswith("neutral: untrusted tier")


def test_trusted_neutral_and_untrusted_failure_do_not_claim_inertness() -> None:
    trusted_neutral = decide_approval(_packet(), run_succeeded=True, tier="trusted")
    assert trusted_neutral.verdict == "neutral"
    assert "untrusted" not in trusted_neutral.reason

    untrusted_failure = decide_approval(
        _packet(findings=[_finding("Major")]), run_succeeded=True, tier="untrusted"
    )
    assert untrusted_failure.verdict == "failure"
    assert "untrusted tier" not in untrusted_failure.reason


def test_reason_distinguishes_missing_findings_from_attested_findings() -> None:
    empty = decide_approval(_packet(), run_succeeded=True, tier="trusted")
    assert empty.reason == "neutral: no typed findings to attest to the review"

    attested = decide_approval(
        _packet(findings=[_finding("Minor")]), run_succeeded=True, tier="trusted"
    )
    assert attested.verdict == "success"
    assert attested.reason == "success: derived from typed findings and run state"


# -- auto-merge routing ---------------------------------------------------------------


def test_complete_low_lane_packet_routes_to_low_risk_passing() -> None:
    packet = _trusted_success(_packet(blast_radius=_blast("low", {})))
    assert select_rule_id(packet) == "low_risk_passing"


@pytest.mark.parametrize("inputs_gate", [False, None], ids=["inputs-failed", "inputs-unmeasured"])
def test_a_checklist_whose_inputs_gate_is_not_true_never_routes_to_merge(
    inputs_gate: bool | None,
) -> None:
    packet = _trusted_success(_packet(blast_radius=_blast("low", {"inputs": inputs_gate})))
    assert select_rule_id(packet) not in {"low_risk_passing", "clean_pass"}


def test_clean_pass_accepts_a_measured_failure_on_a_medium_lane() -> None:
    packet = _trusted_success(_packet(blast_radius=_blast("medium", {"tests": False})))
    assert select_rule_id(packet) == "clean_pass"


def test_clean_pass_refuses_an_unmeasured_gate() -> None:
    packet = _trusted_success(_packet(blast_radius=_blast("medium", {"tests": None})))
    assert select_rule_id(packet) != "clean_pass"


def test_clean_pass_refuses_a_low_lane_with_a_failed_gate() -> None:
    packet = _trusted_success(_packet(blast_radius=_blast("low", {"tests": False})))
    assert select_rule_id(packet) not in {"low_risk_passing", "clean_pass"}


def test_clean_pass_refuses_a_forbidden_auto_merge_lane() -> None:
    packet = _trusted_success(
        _packet(blast_radius=_blast("medium", {}, auto_merge_lane="forbidden"))
    )
    assert select_rule_id(packet) != "clean_pass"


def test_clean_pass_refuses_an_incomplete_checklist() -> None:
    blast = _blast("medium", {})
    blast = blast.model_copy(update={"checklist": blast.checklist[:-1]})
    packet = _trusted_success(_packet(blast_radius=blast))
    assert select_rule_id(packet) != "clean_pass"
