"""Risk-based lens routing against registry trigger signals (AP4)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.registry import Registry, load_registry

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from mergecraft.agents.registry import AgentBinding
    from mergecraft.classify.change_classifier import ChangeClassification
    from mergecraft.config.settings import RepoSettings

RiskBand = Literal["low", "medium", "high"]

_LANE_RANK: dict[RiskBand, int] = {"low": 0, "medium": 1, "high": 2}

LENS_ROUTING_STEP4_NOTE = (
    "\n\n   **Classifier routing (AP4):** after checkout, run the deterministic change "
    "classifier (`classify_change`) and lens router (`route_lenses`) against the diff "
    "payload. Treat `selected_lens_ids` as the registry-backed starting set of themed "
    "lenses — each entry includes a recorded reason. You may add subsystem lenses or omit "
    "a selected lens only after investigating why routing flagged it; skipped lenses are "
    "recorded with reasons and are as informative as selected ones. Trivial doc-only diffs "
    "route zero lenses — skip specialists per step 3."
)


class LensRoutingEntry(BaseModel):
    """One lens row in a routing decision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    lens_id: str
    selected: bool
    reason: str


class LensRoutingDecision(BaseModel):
    """Full routing outcome covering every registry lens."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    selected_lens_ids: tuple[str, ...]
    entries: tuple[LensRoutingEntry, ...]


def load_routing_registry(
    *,
    settings: RepoSettings,
    repo_root: Path | None = None,
) -> Registry:
    """Load the agent registry including lens bindings and trigger metadata."""
    registry = load_registry(settings=settings, repo_root=repo_root)
    registry.validate()
    return registry


def _category_signals(classification: ChangeClassification) -> set[str]:
    categories = classification.change_map.get("categories")
    signals = set(classification.blast_radius.categories)
    if isinstance(categories, list):
        signals.update(str(item) for item in categories)
    return signals


def _matches_triggers(
    binding: AgentBinding,
    classification: ChangeClassification,
) -> tuple[bool, str]:
    triggers = binding.triggers
    if triggers is None:
        return False, "lens has no trigger metadata"

    categories = _category_signals(classification)
    matched: list[str] = []

    if triggers.categories:
        overlap = [cat for cat in triggers.categories if cat in categories]
        if overlap:
            matched.append(f"categories {', '.join(overlap)}")

    if (
        triggers.min_risk_band is not None
        and _LANE_RANK[classification.risk_band] >= _LANE_RANK[triggers.min_risk_band]
    ):
        matched.append(f"risk_band {classification.risk_band} >= {triggers.min_risk_band}")

    if not matched:
        if triggers.categories and triggers.min_risk_band is not None:
            return (
                False,
                "no category overlap and risk_band below minRiskBand",
            )
        if triggers.categories:
            return False, f"no category overlap (saw {', '.join(sorted(categories)) or 'none'})"
        if triggers.min_risk_band is not None:
            return (
                False,
                f"risk_band {classification.risk_band} below minRiskBand {triggers.min_risk_band}",
            )
        return False, "empty trigger metadata"

    return True, "; ".join(matched)


def route_lenses(
    classification: ChangeClassification,
    *,
    registry: Registry,
) -> LensRoutingDecision:
    """Intersect classifier output with registry lens triggers; record all decisions."""
    lens_bindings = sorted(registry.iter_lens_bindings(), key=lambda binding: binding.lens or "")
    if classification.is_trivial:
        entries = tuple(
            LensRoutingEntry(
                lens_id=binding.lens or binding.agent_id,
                selected=False,
                reason="trivial change — specialist lenses skipped",
            )
            for binding in lens_bindings
            if binding.lens is not None
        )
        return LensRoutingDecision(selected_lens_ids=(), entries=entries)

    selected: list[str] = []
    entries_list: list[LensRoutingEntry] = []
    for binding in lens_bindings:
        lens_id = binding.lens
        if lens_id is None:
            continue
        matched, reason = _matches_triggers(binding, classification)
        if matched:
            selected.append(lens_id)
            entries_list.append(LensRoutingEntry(lens_id=lens_id, selected=True, reason=reason))
        else:
            entries_list.append(LensRoutingEntry(lens_id=lens_id, selected=False, reason=reason))

    return LensRoutingDecision(
        selected_lens_ids=tuple(selected),
        entries=tuple(entries_list),
    )


def route_lenses_complement(
    classification: ChangeClassification,
    *,
    registry: Registry,
    prior_dispatched_lens_ids: Sequence[str],
    dispatch_budget: int,
) -> LensRoutingDecision:
    """Bias routing toward lenses that did not run in the prior round (RC9)."""
    baseline = route_lenses(classification, registry=registry)
    if classification.is_trivial or dispatch_budget <= 0:
        return baseline

    prior = frozenset(prior_dispatched_lens_ids)
    complement = [lid for lid in baseline.selected_lens_ids if lid not in prior]
    repeat = [lid for lid in baseline.selected_lens_ids if lid in prior]

    selected: list[str] = []
    for lens_id in complement:
        if len(selected) >= dispatch_budget:
            break
        selected.append(lens_id)

    if not complement:
        for lens_id in repeat:
            if len(selected) >= dispatch_budget:
                break
            selected.append(lens_id)

    selected_set = frozenset(selected)
    entries = tuple(
        LensRoutingEntry(
            lens_id=entry.lens_id,
            selected=entry.lens_id in selected_set,
            reason=(
                f"complement routing: {entry.reason}"
                if entry.lens_id in selected_set and entry.lens_id in complement
                else entry.reason
            ),
        )
        for entry in baseline.entries
    )
    return LensRoutingDecision(
        selected_lens_ids=tuple(selected),
        entries=entries,
    )


def lens_id_from_agent_id(agent_id: str) -> str | None:
    """Return the lens id when ``agent_id`` is a lens-scoped reviewer binding."""
    prefix = "lens-"
    if agent_id.startswith(prefix):
        return agent_id[len(prefix) :]
    return None


__all__ = [
    "LENS_ROUTING_STEP4_NOTE",
    "LensRoutingDecision",
    "LensRoutingEntry",
    "lens_id_from_agent_id",
    "load_routing_registry",
    "route_lenses",
    "route_lenses_complement",
]
