"""Assemble blast-radius / risk grade for the evidence packet (#1489)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.classify.risk import combine_risk_lanes
from mergecraft.classify.risk_jev import evaluate_jev_risk, risk_jev_client
from mergecraft.evidence.run_packet import classify_run_blast_radius

if TYPE_CHECKING:
    from mergecraft.classify import BlastRadiusClassification
    from mergecraft.classify.blast_radius import FixProofSignal, RuleSet, ScopeSignal
    from mergecraft.config.settings import RepoSettings, RiskSettings
    from mergecraft.mcp.tool_state import ToolState


async def resolve_run_risk_classification(
    diff_text: str,
    *,
    scope: ScopeSignal,
    fix_proof: FixProofSignal,
    risk: RiskSettings,
    rule_set: RuleSet | None,
    settings: RepoSettings,
    tool_state: ToolState | None = None,
) -> BlastRadiusClassification | None:
    """Classify the run diff; optionally raise the lane with Jev ``risk/v1``."""
    deterministic = classify_run_blast_radius(
        diff_text, scope=scope, fix_proof=fix_proof, rule_set=rule_set or None
    )
    if deterministic is None:
        return None
    if risk.mode != "jev":
        if tool_state is not None:
            tool_state.risk_classification = deterministic
        return deterministic
    jev_reasons, jev_record = await evaluate_jev_risk(
        risk_jev_client(settings),
        diff_excerpt=diff_text,
        floor=deterministic.lane,
    )
    combined = combine_risk_lanes(deterministic, jev_reasons, jev_record=jev_record)
    if tool_state is not None:
        tool_state.risk_classification = combined
    return combined


__all__ = ["resolve_run_risk_classification"]
