"""Frozen per-run trust posture — one derivation, read everywhere (#SM5)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from mergecraft.analyzers.trust import AnalyzersMode
from mergecraft.config.trust_policy import AuthorGateStatus, TrustPolicy

if TYPE_CHECKING:
    from mergecraft.mcp.tool_state import ToolState

TrustTierName = Literal["trusted", "untrusted"]


@dataclass(frozen=True, slots=True)
class TrustPosture:
    """Execution vs authority trust and analyzer posture for one run."""

    execution_trust: TrustTierName
    authority_trust: TrustTierName
    analyzers_mode: AnalyzersMode
    self_review_level: str
    author_gate_status: AuthorGateStatus
    policy: TrustPolicy | None = None

    def may_approve_on_github(self) -> bool:
        return self.authority_trust == "trusted"

    def may_run_full_analyzers(self) -> bool:
        return self.execution_trust == "trusted" and self.analyzers_mode in {"auto", "full"}


def trust_posture_from_tool_state(
    tool_state: ToolState,
    *,
    analyzers_mode: AnalyzersMode | None = None,
) -> TrustPosture:
    """Read posture fields stamped once on ``ToolState`` (fail-closed defaults)."""
    tier = (tool_state.trust_tier or "untrusted").lower()
    authority = (tool_state.authority_trust or tool_state.trust_tier or "untrusted").lower()
    mode_raw = (analyzers_mode or tool_state.run_manifest_trust.get("analyzers_mode") or "auto").lower()
    analyzers: AnalyzersMode = "auto"
    if mode_raw in {"off", "auto", "full", "untrusted-only"}:
        analyzers = mode_raw  # type: ignore[assignment]
    gate = "not-configured"
    if tool_state.agent_sandbox_decision is not None:
        gate = tool_state.agent_sandbox_decision.author_gate
    return TrustPosture(
        execution_trust="trusted" if tier == "trusted" else "untrusted",
        authority_trust="trusted" if authority == "trusted" else "untrusted",
        analyzers_mode=analyzers,
        self_review_level=tool_state.trust_self_review_level or "off",
        author_gate_status=gate,  # type: ignore[arg-type]
    )


__all__ = ["TrustPosture", "trust_posture_from_tool_state"]
