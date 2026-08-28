"""Two gate regressions from the lane C authority work, and their invariants.

Both were reported on PR #523 and both were real.

**One definition of a passing check.** ``has_failed_required_static_check``
carried its own allowlist, which omitted ``satisfied-by-ci`` — the status a
declared CI check run produces when it proves a gate mergeCraft could not run
here (#36 / #464). ``AnalyzerOutcome.passed`` accepted it, so the two readers
disagreed and a repo declaring ``ciEvidence`` had its terminal approve rejected
on evidence CI had already supplied. The allowlist also carried
``not_applicable``, which is absent from ``CheckStatus`` and emitted by no
producer. Both now read ``PASSING_CHECK_STATUSES``.

**A reachable positive-evidence path.** ``_is_low_risk_passing`` required an
*empty* finding list alongside a ``success`` verdict, but
``_decide_approval_from_findings`` returns ``"neutral"`` for an empty list and
``"success"`` only for a non-empty one — a non-empty list is the attestation
that the review ran. The two conditions were mutually exclusive, so no packet
built by ``build_run_packet`` could select ``low_risk_passing`` and the
``auto_merge`` row was unreachable in production. The predicate now reads
blockers, which is the condition that was meant.
"""

from __future__ import annotations

import typing
from typing import TYPE_CHECKING

import pytest

from mergecraft.analyzers.run import PASSING_CHECK_STATUSES, AnalyzerOutcome, CheckStatus

if TYPE_CHECKING:
    from pathlib import Path

_VOCABULARY: tuple[str, ...] = tuple(sorted(typing.get_args(CheckStatus)))


def test_the_passing_set_is_drawn_from_the_check_status_vocabulary() -> None:
    """A passing status must be a real status, or the gate allows a phantom."""
    assert set(_VOCABULARY) >= PASSING_CHECK_STATUSES
    assert "not_applicable" not in PASSING_CHECK_STATUSES


@pytest.mark.parametrize("status", _VOCABULARY)
def test_both_readers_agree_on_every_status(status: str) -> None:
    """The analyzer view and the gate view of "passing" cannot diverge again.

    This is the regression guard, and it is parametrised over the whole closed
    vocabulary rather than over a representative: the original defect was one
    member of that vocabulary being handled differently by two readers, which a
    single hand-picked case would not have caught.
    """
    from mergecraft.agents.gates import has_failed_required_static_check

    outcome = AnalyzerOutcome(name="lint", command="make lint", status=status, output="")
    gate_blocks = has_failed_required_static_check([{"name": "lint", "status": status}])
    assert outcome.passed is not gate_blocks, (
        f"{status!r}: analyzer says passed={outcome.passed}, gate blocks={gate_blocks}"
    )


def test_ci_substituted_gate_does_not_reject_the_terminal_approve() -> None:
    """End to end: a green CI substitution must not fail the approve gate.

    The unit above pins the predicate; this pins the consequence, which is
    where the defect was actually felt — ``validate_submission`` refusing an
    ``approve`` with ``approve_with_failed_required_gate``.
    """
    from mergecraft.mcp.verdict import build_validation_state, validate_submission

    state = build_validation_state(static_checks=[{"name": "lint", "status": "satisfied-by-ci"}])
    result = validate_submission(
        {"verdict": "approve", "summary": "no findings", "findings": []},
        state=state,
    )

    assert result.accepted, result.rejection_reason


def test_a_failed_gate_still_rejects_the_terminal_approve() -> None:
    """Guard the guard: widening the allowlist must not open the gate."""
    from mergecraft.mcp.verdict import (
        REJECTION_APPROVE_FAILED_GATE,
        build_validation_state,
        validate_submission,
    )

    state = build_validation_state(static_checks=[{"name": "lint", "status": "failed"}])
    result = validate_submission(
        {"verdict": "approve", "summary": "no findings", "findings": []},
        state=state,
    )

    assert not result.accepted
    assert result.rejection_reason == REJECTION_APPROVE_FAILED_GATE


_LOW_RISK_DIFF = (
    "diff --git a/docs/notes.md b/docs/notes.md\n"
    "--- a/docs/notes.md\n"
    "+++ b/docs/notes.md\n"
    "@@ -1 +1 @@\n"
    "-before\n"
    "+after\n"
)


def test_low_risk_passing_is_reachable_from_build_run_packet(tmp_path: Path) -> None:
    """A clean low-risk packet must be able to select ``low_risk_passing``.

    Driven through ``build_run_packet`` on purpose. The pre-existing coverage
    hand-built a packet with an empty finding list and a hand-attached
    ``success`` decision — a combination the builder cannot produce — so it
    passed while the rule was unreachable in production.
    """
    from tests.evidence.test_run_packet import _make_ctx

    from mergecraft.agents.gates import select_rule_id
    from mergecraft.evidence.run_packet import build_run_packet
    from mergecraft.evidence.trajectory import record_tool_call

    ctx = _make_ctx(tmp_path, diff_text=_LOW_RISK_DIFF)
    # A run that verified after its last write. Without this the trajectory
    # auditor raises ``no-post-edit-verification`` at ``Major``, which is a
    # blocker and would mask the reachability this test is about.
    record_tool_call(ctx.tool_state, tool="run_static_checks", arguments={}, ok=True)
    packet = build_run_packet(ctx, change_id="acme/demo#42", run_succeeded=True)

    assert packet.findings, "a success verdict requires attested findings"
    assert packet.blast_radius is not None
    assert packet.blast_radius.lane == "low"
    assert packet.decision is not None
    assert packet.decision.verdict == "success"
    assert select_rule_id(packet) == "low_risk_passing"


def test_a_blocking_finding_still_denies_low_risk_passing(tmp_path: Path) -> None:
    """Reading blockers rather than emptiness must not widen the rule."""
    from tests.evidence.test_run_packet import _make_ctx

    from mergecraft.agents.gates import _is_low_risk_passing
    from mergecraft.analyzers.finding import make_finding
    from mergecraft.evidence.run_packet import build_run_packet

    blocker = make_finding(
        tool="ruff",
        rule_id="E999",
        category="Functional Correctness",
        severity="Major",
        confidence="certain",
        message="syntax error",
        path="docs/notes.md",
        start_line=1,
        end_line=1,
        source="analyzer",
    )
    ctx = _make_ctx(tmp_path, diff_text=_LOW_RISK_DIFF)
    packet = build_run_packet(
        ctx, change_id="acme/demo#42", run_succeeded=True, extra_findings=[blocker]
    )

    assert not _is_low_risk_passing(packet)
