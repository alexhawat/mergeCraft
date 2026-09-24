"""The record must name the skipped reviewer slot and who produced the verdict.

On a run where one roster slot was skipped for missing credentials and the
reviewer that did run submitted a typed ``request_changes`` verdict, the record
said "no credentialed reviewer ran — the review is `inconclusive`" beside a
published CHANGES_REQUESTED review. That is a claim the run cannot make: a
reviewer ran. The record must instead name the skipped slot and the model that
produced the verdict, and state no outcome — the reconciled ``Outcome`` line is
the only outcome claim.

The "no credentialed reviewer ran" wording stays for a run with no typed
terminal verdict, and the demotion of an approval-shaped ``Outcome`` is
unchanged.
"""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.agents.gates import TRUSTED_PACKET_DECIDED_BY
from mergecraft.evidence.build import build_packet
from mergecraft.evidence.packet import Decision
from mergecraft.findings.ledger import render_deterministic_review_block
from mergecraft.run_outcome import RunOutcome
from tests.review_record.conftest import make_scoped_finding

_MODEL = "openai/gpt-5.6-terra"
_MAJOR_MESSAGE = "Unchecked null dereference in the request handler."
_CREDENTIAL_GAP = (
    "reviewer 'reviewer' slot p0 skipped for missing credentials: "
    "provider 'nous', model 'nous/tencent/hy3'"
)
_ANALYZER_SUMMARY = "2 ran; 7 skipped (shell: disabled); lock deadbeef"
_AGENT_SUMMARY = "One Major finding; requesting changes."
_NO_CREDENTIALED_REVIEWER = "no credentialed reviewer ran"
_NOT_AN_APPROVAL = "this record is not an approval"
_INTEGRITY_MARKER = "Review integrity"


def _major_finding() -> Any:
    return make_scoped_finding(
        scope="change",
        severity="Major",
        introduced_by_pr="true",
        message=_MAJOR_MESSAGE,
        rule_id="RECORD-PROVENANCE-MAJOR",
    )


def _packet(*, terminal_verdict: str | None) -> Any:
    packet = build_packet(
        change_id="acme/demo#818",
        agent_id="claude",
        agent_version="0.0.1",
        model=_MODEL,
        files_changed=["src/example.py"],
        findings=[_major_finding()],
        deterministic_checks=[],
        self_assessment={"would_approve": False, "sha": "abc123"},
        agent_terminal_verdict=terminal_verdict,
    )
    packet.decision = Decision(
        verdict="neutral",
        reason="agent terminal verdict request_changes; no structural blocker attested",
        decided_by=TRUSTED_PACKET_DECIDED_BY,
    )
    return packet


def _render(packet: Any, **kwargs: Any) -> str:
    return render_deterministic_review_block(
        packet=packet,
        rejection_reason=None,
        run_url="https://example.test/run",
        analyzer_summary=_ANALYZER_SUMMARY,
        agent_summary=_AGENT_SUMMARY,
        credential_degradations=(_CREDENTIAL_GAP,),
        trust_tier="trusted",
        **kwargs,
    )


def _integrity_line(block: str) -> str:
    return next(line for line in block.splitlines() if _INTEGRITY_MARKER in line)


@pytest.mark.xfail(
    reason="green after LG4: the integrity note names the skipped slot and the verdict's model",
    strict=False,
)
def test_skipped_slot_with_a_recorded_verdict_names_the_model() -> None:
    """A reviewer ran and requested changes: the record must not deny it."""
    block = _render(_packet(terminal_verdict="request_changes"))

    assert _CREDENTIAL_GAP in block, "the skipped slot must be named"
    assert _MAJOR_MESSAGE in block
    integrity = _integrity_line(block)
    assert _MODEL in integrity, (
        f"the integrity line must name the model that produced the verdict:\n{integrity}"
    )
    assert _NO_CREDENTIALED_REVIEWER not in block.lower(), (
        f"a reviewer did run; the record must not claim otherwise:\n{block}"
    )
    assert "inconclusive" not in block.lower(), (
        f"the integrity note must state no outcome:\n{block}"
    )
    assert _NOT_AN_APPROVAL in block.lower(), f"the not-an-approval posture must stay:\n{block}"


def test_a_passed_outcome_is_still_reconciled_to_inconclusive() -> None:
    """The demotion control is unchanged: an approval-shaped Outcome is demoted."""
    block = _render(_packet(terminal_verdict="request_changes"), run_outcome=RunOutcome.passed)

    assert "- **Outcome:** `inconclusive`" in block, block


def test_no_recorded_verdict_keeps_the_no_reviewer_wording() -> None:
    """With no typed terminal verdict, the honest wording stays."""
    block = _render(_packet(terminal_verdict=None))

    assert _NO_CREDENTIALED_REVIEWER in block.lower(), block
    assert _NOT_AN_APPROVAL in block.lower(), block
