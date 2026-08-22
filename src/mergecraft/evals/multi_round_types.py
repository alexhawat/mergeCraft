"""Shared multi-round convergence case shapes (W10, RC6).

Types live here so :mod:`mergecraft.evals.store` and
:mod:`mergecraft.evals.convergence_store` do not import each other at module
load time.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

CATEGORY_MULTI_ROUND_CONVERGENCE: str = "multi_round_convergence"


class CaseRoundLedgerEntry(BaseModel):
    """One ledger row for a round in a multi-round convergence case."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(min_length=1)
    state: str = Field(min_length=1)
    round_index: int | None = None


class CaseRoundFinding(BaseModel):
    """One ground-truth finding row with the round it first appeared in."""

    model_config = ConfigDict(extra="forbid")

    fingerprint: str = Field(min_length=1)
    path: str = Field(min_length=1)
    start_line: int
    end_line: int
    body: str = Field(min_length=1)
    first_appeared_round: int = Field(ge=1)


class CaseRound(BaseModel):
    """One review round: diff, recorded findings, and ledger snapshot."""

    model_config = ConfigDict(extra="forbid")

    round_index: int = Field(ge=1)
    diff_text: str = ""
    findings: list[CaseRoundFinding] = Field(default_factory=list)
    ledger: list[CaseRoundLedgerEntry] = Field(default_factory=list)
    generated_fingerprints: list[str] = Field(default_factory=list)


__all__ = [
    "CATEGORY_MULTI_ROUND_CONVERGENCE",
    "CaseRound",
    "CaseRoundFinding",
    "CaseRoundLedgerEntry",
]
