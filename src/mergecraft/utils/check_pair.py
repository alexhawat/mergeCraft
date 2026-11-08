"""``mergecraft`` + ``mergecraft-approval`` check pair (#SM7)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

CompletionConclusion = Literal["success", "failure", "neutral", "timed_out"]
ApprovalConclusion = Literal["success", "failure", "neutral"]


@dataclass(frozen=True, slots=True)
class StatusCheckPair:
    """Legal combination of completion and approval check conclusions."""

    completion: CompletionConclusion
    approval: ApprovalConclusion

    def legal(self) -> bool:
        """Completion ``success`` requires approval not ``failure`` on passed runs."""
        if self.completion == "success" and self.approval == "failure":
            return False
        if self.completion == "timed_out":
            return self.approval == "neutral"
        return True


LEGAL_CHECK_PAIRS: frozenset[tuple[CompletionConclusion, ApprovalConclusion]] = frozenset(
    {
        ("success", "success"),
        ("success", "neutral"),
        ("failure", "failure"),
        ("failure", "neutral"),
        ("neutral", "neutral"),
        ("neutral", "failure"),
        ("timed_out", "neutral"),
    }
)


def pair_from_conclusions(
    completion: CompletionConclusion,
    approval: ApprovalConclusion,
) -> StatusCheckPair:
    return StatusCheckPair(completion=completion, approval=approval)


__all__ = ["LEGAL_CHECK_PAIRS", "StatusCheckPair", "pair_from_conclusions"]
