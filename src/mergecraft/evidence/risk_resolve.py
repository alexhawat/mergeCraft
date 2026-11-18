"""Assemble blast-radius / risk grade for the evidence packet (#1489)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.classify.risk import combine_risk_lanes
from mergecraft.classify.risk_jev import evaluate_jev_risk
from mergecraft.evidence.run_packet import classify_run_blast_radius
from mergecraft.jev.client import AsyncJevClient

if TYPE_CHECKING:
    from mergecraft.classify import BlastRadiusClassification
    from mergecraft.classify.blast_radius import FixProofSignal, RuleSet, ScopeSignal
    from mergecraft.config.settings import RepoSettings, RiskSettings, TrustTier
    from mergecraft.mcp.tool_state import ToolState


async def resolve_run_risk_classification(
    diff_text: str,
    *,
    scope: ScopeSignal,
    fix_proof: FixProofSignal,
    risk: RiskSettings,
    rule_set: RuleSet | None,
    settings: RepoSettings,
    trust_tier: TrustTier = "untrusted",
    tool_state: ToolState | None = None,
) -> BlastRadiusClassification | None:
    """Classify the run diff; optionally raise the lane with Jev ``risk/v1``."""
    classification = classify_run_blast_radius(
        diff_text, scope=scope, fix_proof=fix_proof, rule_set=rule_set
    )
    if classification is None:
        return None
    if risk.mode == "jev":
        jev_reasons, jev_record = await evaluate_jev_risk(
            AsyncJevClient(settings=settings.jev),
            diff_excerpt=diff_text,
            floor=classification.lane,
            trust_tier=trust_tier,
        )
        classification = combine_risk_lanes(classification, jev_reasons, jev_record=jev_record)
    if tool_state is not None:
        tool_state.risk_classification = classification
    return classification


__all__ = ["resolve_run_risk_classification"]
