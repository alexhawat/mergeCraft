"""Multi-round convergence case materialization (W10, RC6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.evals.multi_round_types import (
    CATEGORY_MULTI_ROUND_CONVERGENCE,
    CaseRound,
    CaseRoundFinding,
    CaseRoundLedgerEntry,
)
from mergecraft.findings.lifecycle import validate_lifecycle_state

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.evals.convergence import ConvergenceRound
    from mergecraft.evals.store import Case


def convergence_rounds_from_case(case: Case) -> list[ConvergenceRound]:
    """Materialize :class:`CaseRound` rows as :class:`ConvergenceRound` inputs."""
    if not case.rounds:
        msg = f"case {case.id!r} has no multi-round corpus"
        raise ValueError(msg)
    from mergecraft.evals.convergence import ConvergenceRound
    from mergecraft.findings.ledger import FindingLedger

    materialized: list[ConvergenceRound] = []
    for round_row in sorted(case.rounds, key=lambda row: row.round_index):
        ledger = FindingLedger()
        for entry in round_row.ledger:
            ledger.record(
                entry.fingerprint,
                validate_lifecycle_state(entry.state),
                source=case.id,
                round_index=entry.round_index or round_row.round_index,
            )
        finding_rows = [row.model_dump() for row in round_row.findings]
        generated = list(round_row.generated_fingerprints)
        if not generated:
            generated = [row.fingerprint for row in round_row.findings]
        materialized.append(
            ConvergenceRound(
                round_index=round_row.round_index,
                ledger=ledger,
                findings=finding_rows,
                generated_fingerprints=generated,
                diff_text=round_row.diff_text,
            )
        )
    return materialized


def list_multi_round_cases(
    bank_dir: Path,
    *,
    category: str = CATEGORY_MULTI_ROUND_CONVERGENCE,
) -> list[Case]:
    """Return bank cases with a multi-round convergence corpus, sorted by id."""
    from mergecraft.evals.store import list_cases

    cases = [case for case in list_cases(bank_dir, category=category) if case.is_multi_round]
    cases.sort(key=lambda row: row.id)
    return cases


__all__ = [
    "CATEGORY_MULTI_ROUND_CONVERGENCE",
    "CaseRound",
    "CaseRoundFinding",
    "CaseRoundLedgerEntry",
    "convergence_rounds_from_case",
    "list_multi_round_cases",
]
