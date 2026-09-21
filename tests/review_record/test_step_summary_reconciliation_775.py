"""Regression (#784 review) — the step-summary header table must match the record.

`render_step_summary` renders a coarse header table (`| Outcome | … |`,
`| Diagnostic | … |`) **plus** the embedded deterministic record. It used to
demote the header cells only on a credential gap. A completed run that
submitted a `request_changes` terminal verdict with no credential degradation
kept `Outcome: success` / `Diagnostic: approved` in the outer table while the
embedded record demoted to `inconclusive` — two postures in one summary.

The fix introduces one shared predicate (`record_is_not_an_approval`) and one
reconciler (`reconcile_outcome`) so both surfaces agree. These tests pin the
outcome of that agreement on the rendered text: the header cells and the
embedded record lines must carry the same posture, and the reconciliation must
leave a genuine failure and a `no_verdict` label intact.
"""

from __future__ import annotations

import re
from typing import Any, Literal

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings.ledger import DETERMINISTIC_RECORD_MARKER
from mergecraft.mcp.verdict import VerdictDiagnostic
from mergecraft.run_outcome import RunOutcome
from mergecraft.utils.step_summary import render_step_summary

_Verdict = Literal["success", "failure", "neutral"]
_TerminalVerdict = Literal["approve", "request_changes"]

_HEADER_ROW = re.compile(r"^\| (?P<field>[^|]+?) \| (?P<value>.+?) \|$")
_RECORD_OUTCOME = re.compile(r"^- \*\*Outcome:\*\* `([^`]+)`", re.MULTILINE)
_RECORD_DIAGNOSTIC = re.compile(r"^- \*\*Verdict diagnostic:\*\* `([^`]+)`", re.MULTILINE)

# Literal rendered lines, in the style of the credential-gap suite: the coarse
# header cells and the embedded record lines are asserted by their exact text.
_HEADER_OUTCOME_SUCCESS = "| Outcome | `success` |"
_HEADER_DIAGNOSTIC_APPROVED = "| Diagnostic | `approved` |"
_RECORD_OUTCOME_PASSED = "- **Outcome:** `passed`"
_RECORD_DIAGNOSTIC_APPROVED = "- **Verdict diagnostic:** `approved`"

_CREDENTIAL_GAP = (
    "reviewer 'reviewer' slot p0 skipped for missing credentials: "
    "provider 'auto', model 'auto/efficient'; provider 'auto' has no credential step "
    "in mergecraft.yml for model 'auto/efficient'"
)
_TERMINAL_REQUEST_CHANGES_REASON = (
    "neutral: agent terminal verdict request_changes; no structural blocker attested"
)


def _packet(
    *,
    decision_verdict: _Verdict | None = None,
    decision_reason: str | None = None,
    terminal_verdict: _TerminalVerdict | None = None,
) -> Any:
    packet = build_packet(
        change_id="acme/demo#784",
        agent_id="claude",
        agent_version="0.0.1",
        model="claude-sonnet-4-5",
        files_changed=["src/example.py"],
        findings=[],
        deterministic_checks=[],
        self_assessment={"would_approve": True, "sha": "abc123"},
        agent_terminal_verdict=terminal_verdict,
    )
    if decision_verdict is not None:
        packet.decision = Decision(
            verdict=decision_verdict,
            reason=decision_reason or "",
            decided_by=TRUSTED_PACKET_DECIDED_BY,
        )
    return packet


def _render(packet: Any, **kwargs: Any) -> str:
    return render_step_summary(
        packet=packet,
        rejection_reason=None,
        run_url="https://example.test/run",
        **kwargs,
    )


def _header_cells(body: str) -> dict[str, str]:
    """Parse the coarse header table lines that precede the embedded record."""
    header = body.partition(DETERMINISTIC_RECORD_MARKER)[0]
    cells: dict[str, str] = {}
    for line in header.splitlines():
        match = _HEADER_ROW.match(line)
        if match:
            cells[match.group("field").strip()] = match.group("value").strip().strip("`")
    return cells


def _record_cell(body: str, pattern: re.Pattern[str]) -> str | None:
    match = pattern.search(body)
    return match.group(1) if match else None


def test_header_and_record_agree_on_a_request_changes_terminal_verdict() -> None:
    """The reported bug: no credential gap, yet a terminal `request_changes`."""
    body = _render(
        _packet(
            decision_verdict="neutral",
            decision_reason=_TERMINAL_REQUEST_CHANGES_REASON,
            terminal_verdict="request_changes",
        ),
        outcome_label="success",
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
        credential_degradations=None,
        trust_tier="trusted",
    )

    cells = _header_cells(body)
    assert cells["Outcome"] == "inconclusive", (
        f"the header must not claim success beside a request_changes terminal verdict:\n{body}"
    )
    assert cells["Diagnostic"] == "inconclusive", (
        f"the header must not claim approved beside a request_changes terminal verdict:\n{body}"
    )
    assert _record_cell(body, _RECORD_OUTCOME) == "inconclusive", body
    assert _record_cell(body, _RECORD_DIAGNOSTIC) == "inconclusive", body
    assert _HEADER_OUTCOME_SUCCESS not in body, body
    assert _HEADER_DIAGNOSTIC_APPROVED not in body, body
    assert _RECORD_OUTCOME_PASSED not in body, body
    assert _RECORD_DIAGNOSTIC_APPROVED not in body, body


def test_header_and_record_agree_on_a_credential_gap() -> None:
    """A skipped credentialed reviewer slot demotes both surfaces, as before."""
    body = _render(
        _packet(decision_verdict="success", decision_reason="approved"),
        outcome_label="success",
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
        credential_degradations=(_CREDENTIAL_GAP,),
        trust_tier="trusted",
    )

    cells = _header_cells(body)
    assert cells["Outcome"] == "inconclusive", body
    assert cells["Diagnostic"] == "inconclusive", body
    assert _record_cell(body, _RECORD_OUTCOME) == "inconclusive", body
    assert _record_cell(body, _RECORD_DIAGNOSTIC) == "inconclusive", body
    assert _HEADER_OUTCOME_SUCCESS not in body, body
    assert _HEADER_DIAGNOSTIC_APPROVED not in body, body
    assert _RECORD_OUTCOME_PASSED not in body, body
    assert _RECORD_DIAGNOSTIC_APPROVED not in body, body


def test_header_and_record_keep_a_clean_success() -> None:
    """A run that reached a credentialed reviewer still reads as an approval."""
    body = _render(
        _packet(decision_verdict="success", decision_reason="approved"),
        outcome_label="success",
        run_outcome=RunOutcome.passed,
        verdict_diagnostic=VerdictDiagnostic.approved,
        credential_degradations=None,
        trust_tier="trusted",
    )

    cells = _header_cells(body)
    assert cells["Outcome"] == "success", body
    assert cells["Diagnostic"] == "approved", body
    assert _record_cell(body, _RECORD_OUTCOME) == "passed", body
    assert _record_cell(body, _RECORD_DIAGNOSTIC) == "approved", body
    assert _HEADER_OUTCOME_SUCCESS in body, body
    assert _HEADER_DIAGNOSTIC_APPROVED in body, body
    assert _RECORD_OUTCOME_PASSED in body, body
    assert _RECORD_DIAGNOSTIC_APPROVED in body, body
    assert "inconclusive" not in body, f"a clean success must not be demoted:\n{body}"


def test_header_and_record_leave_a_genuine_failure_intact() -> None:
    """The reconciliation must never mask a real failure behind `inconclusive`."""
    body = _render(
        _packet(decision_verdict="failure", decision_reason="provider_failure"),
        outcome_label="failure",
        run_outcome=RunOutcome.failed,
        verdict_diagnostic=VerdictDiagnostic.provider_failure,
        credential_degradations=None,
        trust_tier="trusted",
    )

    cells = _header_cells(body)
    assert cells["Outcome"] == "failure", body
    assert cells["Diagnostic"] == "provider_failure", body
    assert _record_cell(body, _RECORD_OUTCOME) == "failed", body
    assert _record_cell(body, _RECORD_DIAGNOSTIC) == "provider_failure", body
    assert "inconclusive" not in body, f"a genuine failure must not be demoted:\n{body}"


def test_header_and_record_leave_no_verdict_intact() -> None:
    """A run with no decision reports `no_verdict`, not a demoted `inconclusive`."""
    body = _render(
        _packet(),
        outcome_label="no_verdict",
        run_outcome=RunOutcome.inconclusive,
        verdict_diagnostic=VerdictDiagnostic.provider_success_without_submission,
        credential_degradations=None,
        trust_tier="trusted",
    )

    cells = _header_cells(body)
    assert cells["Outcome"] == "no_verdict", (
        f"a no_verdict label must survive reconciliation unchanged:\n{body}"
    )
    assert cells["Diagnostic"] == "provider_success_without_submission", body
    assert cells["Verdict"] == "(none)", body
    assert _record_cell(body, _RECORD_OUTCOME) == "inconclusive", body
    assert _record_cell(body, _RECORD_DIAGNOSTIC) == "provider_success_without_submission", body
    assert _HEADER_OUTCOME_SUCCESS not in body, body
    assert _HEADER_DIAGNOSTIC_APPROVED not in body, body
    assert _RECORD_OUTCOME_PASSED not in body, body
    assert _RECORD_DIAGNOSTIC_APPROVED not in body, body
