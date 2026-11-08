"""Composed verdict projection — one monotone path to check conclusions (#SM4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mergecraft.agents.gates import decide_approval
from mergecraft.run_outcome import RunOutcome, run_succeeded_for_outcome
from mergecraft.utils.status_checks import Conclusion

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding
    from mergecraft.config.settings import TrustTier
    from mergecraft.evidence.packet import MergeEvidencePacket

StructuralConclusion = Conclusion
CompletionConclusion = Literal["success", "failure", "neutral", "timed_out"]


@dataclass(frozen=True, slots=True)
class ComposedRunVerdict:
    """Approval + completion conclusions derived together."""

    run_outcome: RunOutcome
    structural: StructuralConclusion
    completion: CompletionConclusion
    run_succeeded: bool


def project_structural_conclusion(
    findings: list[Finding] | MergeEvidencePacket,
    *,
    run_succeeded: bool,
    tier: TrustTier,
) -> StructuralConclusion:
    result = decide_approval(findings, run_succeeded=run_succeeded, tier=tier)
    if isinstance(result, str):
        return result
    return result.verdict


def project_run_verdict(
    findings: list[Finding] | MergeEvidencePacket,
    *,
    outcome: RunOutcome,
    tier: TrustTier,
) -> ComposedRunVerdict:
    """Map run outcome + findings to both check conclusions (monotone)."""
    from mergecraft.run_outcome import RUN_OUTCOME_CONCLUSION

    run_succeeded = run_succeeded_for_outcome(outcome)
    structural = project_structural_conclusion(findings, run_succeeded=run_succeeded, tier=tier)
    completion = RUN_OUTCOME_CONCLUSION[outcome]
    return ComposedRunVerdict(
        run_outcome=outcome,
        structural=structural,
        completion=completion,
        run_succeeded=run_succeeded,
    )


__all__ = [
    "ComposedRunVerdict",
    "StructuralConclusion",
    "project_run_verdict",
    "project_structural_conclusion",
]
