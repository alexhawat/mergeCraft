"""Ensemble and shadow dispatch for registry agents (AP3, D7).

``dispatch: ensemble`` runs one binding on two models from its chain; agreement
raises confidence, disagreement routes to the judge. ``dispatch: shadow`` records
alternate-model output via ``evidence.shadow`` without acting on it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, ConfigDict

from mergecraft.agents.registry import AgentRole, resolve_agent_model
from mergecraft.evidence.shadow import ShadowRecord

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.agents.registry import AgentBinding, Registry
    from mergecraft.config.settings import RepoSettings

ExecuteFn = Callable[..., list[dict[str, object]]]


class EnsembleCardinalityError(ValueError):
    """Raised when ensemble/shadow dispatch targets the orchestrator (D7)."""


class ModelRun(BaseModel):
    """Findings returned by one model in an ensemble fan-out."""

    model_config = ConfigDict(extra="forbid")

    model: str
    findings: tuple[dict[str, object], ...] = ()


class EnsembleRun(BaseModel):
    """Per-model results from one ensemble dispatch."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    model_runs: tuple[ModelRun, ...] = ()


class JudgeDispatch(BaseModel):
    """Brief routed to the judge when ensemble models disagree."""

    model_config = ConfigDict(extra="forbid")

    role: Literal["judge"] = "judge"
    brief: str


class EnsembleReconciliation(BaseModel):
    """Merged ensemble outcome — agreement signal or judge escalation."""

    model_config = ConfigDict(extra="forbid")

    agreement: bool
    confidence_boost: float = 0.0
    merged_findings: tuple[dict[str, object], ...] = ()
    judge_dispatch: JudgeDispatch | None = None


@dataclass(frozen=True, slots=True)
class ShadowDispatchResult:
    """Primary findings acted on; shadow findings recorded only."""

    primary_findings: list[dict[str, object]]
    acted_findings: list[dict[str, object]]
    shadow_model: str
    shadow_findings: list[dict[str, object]]


_ENSEMBLE_ELIGIBLE_ROLES: frozenset[AgentRole] = frozenset(
    {
        AgentRole.reviewer,
        AgentRole.verifier,
        AgentRole.judge,
        AgentRole.classifier,
    }
)


def validate_ensemble_eligible(binding: AgentBinding) -> None:
    """Reject ensemble/shadow on orchestrator bindings (D7)."""
    if binding.role is AgentRole.orchestrator:
        msg = (
            f"orchestrator agent {binding.agent_id!r} cannot use ensemble or shadow "
            "dispatch — two orchestrators violate the terminal cardinality rule (D7)"
        )
        raise EnsembleCardinalityError(msg)
    if binding.role not in _ENSEMBLE_ELIGIBLE_ROLES:
        msg = f"agent {binding.agent_id!r} is not eligible for ensemble dispatch"
        raise ValueError(msg)


def plan_ensemble_models(
    binding: AgentBinding,
    *,
    settings: RepoSettings,
) -> tuple[str, str]:
    """Return two distinct runnable slugs from the binding chain."""
    from mergecraft.utils.agent_resolve import pick_runnable_slug_from_chain

    validate_ensemble_eligible(binding)
    chain = list(binding.model_chain)
    if len(chain) < 2:
        msg = f"ensemble dispatch requires at least two models on {binding.agent_id!r}"
        raise ValueError(msg)

    primary = resolve_agent_model(binding, settings=settings).dispatched_model
    secondary: str | None = None
    for slug in chain:
        if slug == binding.model_chain[0]:
            continue
        runnable = pick_runnable_slug_from_chain(
            [slug],
            allow_fallback=settings.allow_fallback,
        )
        if runnable is not None and runnable != primary:
            secondary = runnable
            break

    if secondary is None:
        msg = f"ensemble dispatch could not resolve a second model for {binding.agent_id!r}"
        raise ValueError(msg)

    return primary, secondary


def _cap_findings(
    rows: list[dict[str, object]],
    *,
    budget: int,
    remaining: int,
) -> tuple[list[dict[str, object]], int]:
    if remaining <= 0:
        return [], 0
    capped = rows[:remaining]
    return capped, remaining - len(capped)


def run_ensemble_dispatch(
    binding: AgentBinding,
    *,
    registry: Registry,
    settings: RepoSettings,
    execute: ExecuteFn,
) -> EnsembleRun:
    """Fan out one binding to two models, honouring the binding budget (CC3)."""
    del registry
    validate_ensemble_eligible(binding)
    primary, secondary = plan_ensemble_models(binding, settings=settings)
    remaining = max(binding.budget, 0)
    model_runs: list[ModelRun] = []

    for model in (primary, secondary):
        raw = list(execute(model=model))
        capped, remaining = _cap_findings(raw, budget=binding.budget, remaining=remaining)
        model_runs.append(ModelRun(model=model, findings=tuple(capped)))

    return EnsembleRun(agent_id=binding.agent_id, model_runs=tuple(model_runs))


def _finding_key(row: dict[str, object]) -> tuple[str, str, str]:
    """Identify a finding by its anchor and body.

    ``line`` is part of the identity: the same defect reported at two call
    sites in one file is two findings, and a key without the line collapses
    them. A row with no line keys on ``""``, which cannot collide with any
    line number.
    """
    line = row.get("line")
    return str(row.get("path", "")), str(row.get("body", "")), "" if line is None else str(line)


def reconcile_ensemble(run: EnsembleRun) -> EnsembleReconciliation:
    """Merge ensemble runs — agreement boosts confidence; disagreement → judge."""
    if len(run.model_runs) < 2:
        merged = tuple(run.model_runs[0].findings) if run.model_runs else ()
        return EnsembleReconciliation(agreement=True, merged_findings=merged)

    left, right = run.model_runs[0], run.model_runs[1]
    left_keys = {_finding_key(row) for row in left.findings}
    right_keys = {_finding_key(row) for row in right.findings}
    if left_keys == right_keys:
        # Empty-vs-empty is agreement (both found nothing) but not a
        # confidence boost — there is no corroborated finding set.
        boost = 0.25 if left_keys else 0.0
        return EnsembleReconciliation(
            agreement=True,
            confidence_boost=boost,
            merged_findings=left.findings,
        )

    brief_parts = [
        "Two ensemble models disagreed on findings for the same agent dispatch.",
        "",
        f"### Model {left.model}",
        "",
    ]
    for row in left.findings:
        brief_parts.append(f"- `{row.get('path')}`: {row.get('body')}")
    brief_parts.extend(["", f"### Model {right.model}", ""])
    for row in right.findings:
        brief_parts.append(f"- `{row.get('path')}`: {row.get('body')}")
    brief_parts.append("")
    brief_parts.append("Return confirm / downgrade / drop for each disputed finding.")

    # Union both sides so a finding only the secondary model reported is not
    # confined to the judge brief (D15). Insertion order gives a deterministic
    # merge: left's findings in their own order, then right-only ones in theirs.
    # First occurrence wins, so the primary model's copy of a corroborated
    # finding keeps its severity and evidence.
    unioned: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in (*left.findings, *right.findings):
        unioned.setdefault(_finding_key(row), row)

    return EnsembleReconciliation(
        agreement=False,
        merged_findings=tuple(unioned.values()),
        judge_dispatch=JudgeDispatch(brief="\n".join(brief_parts)),
    )


def _record_ensemble_shadow(
    *,
    record_path: Path,
    run_id: str,
    change_id: str,
    policy_id: str,
    shadow_model: str,
    shadow_findings: list[dict[str, object]],
) -> ShadowRecord:
    record = ShadowRecord(
        run_id=run_id,
        change_id=change_id,
        policy_id=policy_id,
        rule_id="ensemble_shadow",
        action="shadow",
        lane="ensemble",
        repo_area=policy_id,
        metadata={"shadow_model": shadow_model, "shadow_model_findings": shadow_findings},
    )
    record_path.parent.mkdir(parents=True, exist_ok=True)
    with record_path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json())
        handle.write("\n")
    return record


def run_shadow_dispatch(
    binding: AgentBinding,
    *,
    registry: Registry,
    settings: RepoSettings,
    execute: ExecuteFn,
    record_path: Path,
    run_id: str = "ensemble-shadow",
    change_id: str = "shadow-dispatch",
    policy_id: str = "ensemble.shadow",
) -> ShadowDispatchResult:
    """Run primary model for action; record shadow model output only."""
    del registry
    validate_ensemble_eligible(binding)
    primary, secondary = plan_ensemble_models(binding, settings=settings)
    primary_findings = list(execute(model=primary, primary=True))
    shadow_findings = list(execute(model=secondary, primary=False))
    _record_ensemble_shadow(
        record_path=record_path,
        run_id=run_id,
        change_id=change_id,
        policy_id=policy_id,
        shadow_model=secondary,
        shadow_findings=shadow_findings,
    )
    return ShadowDispatchResult(
        primary_findings=primary_findings,
        acted_findings=list(primary_findings),
        shadow_model=secondary,
        shadow_findings=shadow_findings,
    )


__all__ = [
    "EnsembleCardinalityError",
    "EnsembleReconciliation",
    "EnsembleRun",
    "JudgeDispatch",
    "ModelRun",
    "ShadowDispatchResult",
    "plan_ensemble_models",
    "reconcile_ensemble",
    "run_ensemble_dispatch",
    "run_shadow_dispatch",
    "validate_ensemble_eligible",
]
