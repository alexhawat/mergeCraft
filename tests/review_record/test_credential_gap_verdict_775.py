"""F10 / F11 / F12 (#775) — a review that could not run must not read as one that did.

The record is rendered from three independent inputs — the run outcome, the
verdict diagnostic, and the packet decision — and today nothing reconciles
them. When the credentialed reviewer slot is skipped for a missing credential
the run still renders ``Outcome: passed`` beside ``Verdict diagnostic:
approved``, and a the same record can carry a ``request_changes`` terminal
verdict in its decision reason. Each of those reads as a completed review.

The posture is fixed by the operator: ``inconclusive`` is mergeCraft's internal
outcome (GitHub's check conclusion stays ``neutral``), and when no credentialed
reviewer ran the record may not say ``passed`` or ``approved``.
"""

from __future__ import annotations

import re
from typing import Any

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings.ledger import render_deterministic_review_block
from mergecraft.mcp.verdict import VerdictDiagnostic
from mergecraft.run_outcome import RunOutcome

_OUTCOME_PASSED = "- **Outcome:** `passed`"
_DIAGNOSTIC_APPROVED = "- **Verdict diagnostic:** `approved`"
_CREDENTIAL_GAP = (
    "reviewer 'reviewer' slot p0 skipped for missing credentials: "
    "provider 'auto', model 'auto/efficient'; provider 'auto' has no credential step "
    "in mergecraft.yml for model 'auto/efficient'"
)
_ANALYZER_SUMMARY = "2 ran; 7 skipped (shell: disabled); lock deadbeef"
_NO_CREDENTIALED_REVIEWER = re.compile(
    r"no credentialed reviewer|credentialed reviewer did not|reviewer did not run",
    re.IGNORECASE,
)


def _packet(*, decision_verdict: str, decision_reason: str) -> Any:
    packet = build_packet(
        change_id="acme/demo#775",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=[],
        deterministic_checks=[],
        self_assessment={"would_approve": True, "sha": "abc123"},
    )
    packet.decision = Decision(
        verdict=decision_verdict,  # type: ignore[arg-type]
        reason=decision_reason,
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet


def _render(packet: Any, **kwargs: Any) -> str:
    return render_deterministic_review_block(
        packet=packet,
        rejection_reason=None,
        run_url="https://example.test/run",
        **kwargs,
    )


def test_credential_gap_record_reports_inconclusive_not_approval() -> None:
    """F10 / F11 (#775) — no credentialed reviewer means no approval-shaped record."""
    block = _render(
        _packet(decision_verdict="success", decision_reason="approved"),
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
        analyzer_summary=_ANALYZER_SUMMARY,
        credential_degradations=(_CREDENTIAL_GAP,),
        trust_tier="untrusted",
    )

    assert "inconclusive" in block.lower(), (
        f"a run with a skipped reviewer credential must report inconclusive:\n{block}"
    )
    assert _OUTCOME_PASSED not in block, (
        f"the record may not say Outcome: passed when no credentialed reviewer ran:\n{block}"
    )
    assert _DIAGNOSTIC_APPROVED not in block, (
        "the record may not say Verdict diagnostic: approved when no credentialed reviewer "
        f"ran:\n{block}"
    )


def test_credential_gap_record_names_who_participated() -> None:
    """F10 / F11 (#775) — the record says which analyzers ran and that no reviewer did."""
    block = _render(
        _packet(decision_verdict="success", decision_reason="approved"),
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
        analyzer_summary=_ANALYZER_SUMMARY,
        credential_degradations=(_CREDENTIAL_GAP,),
        trust_tier="untrusted",
    )

    assert _CREDENTIAL_GAP in block
    assert _ANALYZER_SUMMARY in block, (
        f"the run output must state which analyzers ran and which were withheld:\n{block}"
    )
    assert _NO_CREDENTIALED_REVIEWER.search(block), (
        "the run output must state that no credentialed reviewer participated:\n" + block
    )


def test_a_complete_run_still_reports_passed_and_approved() -> None:
    """The posture change must not demote a run that did reach a credentialed reviewer."""
    block = _render(
        _packet(decision_verdict="success", decision_reason="approved"),
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
        analyzer_summary=_ANALYZER_SUMMARY,
        credential_degradations=None,
        trust_tier="trusted",
    )

    assert _OUTCOME_PASSED in block
    assert _DIAGNOSTIC_APPROVED in block
    assert _NO_CREDENTIALED_REVIEWER.search(block) is None


def test_record_cannot_carry_passed_approved_and_request_changes_at_once() -> None:
    """F12 (#775) — one record, one answer."""
    block = _render(
        _packet(
            decision_verdict="neutral",
            decision_reason=(
                "agent terminal verdict request_changes; no structural blocker attested"
            ),
        ),
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
    )

    claims = {
        "outcome_passed": _OUTCOME_PASSED in block,
        "diagnostic_approved": _DIAGNOSTIC_APPROVED in block,
        "terminal_request_changes": "request_changes" in block,
    }
    assert sum(claims.values()) < 3, (
        f"one record must not carry all three of passed/approved/request_changes: {claims}\n{block}"
    )


def test_record_does_not_report_passed_beside_a_request_changes_terminal_verdict() -> None:
    """F12 (#775) — the structural outcome and the recorded verdict cannot disagree."""
    block = _render(
        _packet(
            decision_verdict="neutral",
            decision_reason=(
                "agent terminal verdict request_changes; no structural blocker attested"
            ),
        ),
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
    )

    assert not (_OUTCOME_PASSED in block and "request_changes" in block), (
        "a record that names a request_changes terminal verdict may not also read as "
        f"Outcome: passed:\n{block}"
    )
