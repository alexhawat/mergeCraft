"""Fold disposition-ledger and publication into one outcome resolver (#SM1, #SM9)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.run_outcome import RunOutcome, outcome_with_disposition_ledger

if TYPE_CHECKING:
    from mergecraft.evidence.packet import MergeEvidencePacket


def finalize_run_outcome(
    outcome: RunOutcome,
    packet: MergeEvidencePacket | None,
    *,
    disposition_reason: str | None = None,
) -> tuple[RunOutcome, str | None]:
    """Apply publication + disposition downgrades (monotone — never upgrades)."""
    resolved, reason = outcome_with_disposition_ledger(outcome, packet)
    if disposition_reason and resolved is RunOutcome.inconclusive and reason is None:
        return resolved, disposition_reason
    return resolved, reason


__all__ = ["finalize_run_outcome"]
