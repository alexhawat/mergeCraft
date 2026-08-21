"""Policy lifecycle back half — effective set, simulate, conflicts, audit, metrics (#358).

Does not replace schema, enforcement, exceptions, or evidence requirements.
Does not call ``decide_approval()`` (D14). Policy packs are #359.

Module: mergecraft.policy.lifecycle
Depends: dataclasses, json

Exports:
    Classes:
        PolicyConflict — Same-id rules that disagree at the same scope.
        PolicyAuditArtifact — Written audit JSON path.
        SimulationReport — Past-PR trigger results for a proposed rule.
        PolicyMetrics — Trigger / FP / waiver / blocking rates.
    Functions:
        detect_conflicting_policies — Surface silent-merge conflicts.
        simulate_rule — Replay a proposed rule against past PRs.
        write_policy_audit — Persist audit artifacts.
        policy_metrics — Rate numerators against review volume.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from fnmatch import fnmatch
from typing import TYPE_CHECKING, Any, Final

from mergecraft.policy.schema import PolicyRule, parse_rule
from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence
    from pathlib import Path

_ENFORCEMENT_KEY: Final[str] = "enforcement"


@dataclass(frozen=True, slots=True)
class PolicyConflict:
    """Two or more rules that share an id and scope but disagree on enforcement."""

    rule_id: str
    enforcements: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PolicyAuditArtifact:
    """Path of a written policy audit JSON document."""

    path: Path


@dataclass(frozen=True, slots=True)
class SimulationReport:
    """Which past PRs a proposed rule would trigger on."""

    triggered: tuple[int, ...]


@dataclass(frozen=True)
class PolicyMetrics:
    """Lifecycle rates in ``[0.0, 1.0]`` relative to ``reviews``."""

    trigger_rate: float
    false_positive_rate: float
    waiver_rate: float
    blocking_rate: float


def _as_mapping(rule: Mapping[str, Any] | PolicyRule) -> dict[str, Any]:
    if isinstance(rule, PolicyRule):
        return rule.model_dump()
    return dict(rule)


def _scope_key(scope: object) -> tuple[tuple[str, str], ...]:
    if not isinstance(scope, dict):
        return ()
    return tuple(
        sorted((str(key), str(value)) for key, value in scope.items() if value is not None)
    )


def detect_conflicting_policies(
    rules: Sequence[Mapping[str, Any] | PolicyRule],
) -> list[PolicyConflict]:
    """Return same-id, same-scope rules whose enforcement modes disagree."""
    grouped: dict[tuple[str, tuple[tuple[str, str], ...]], set[str]] = {}
    for raw in rules:
        payload = _as_mapping(raw)
        rule_id = str(payload.get("id", ""))
        if not rule_id:
            continue
        key = (rule_id, _scope_key(payload.get("scope")))
        grouped.setdefault(key, set()).add(str(payload.get(_ENFORCEMENT_KEY, "advisory")))
    conflicts: list[PolicyConflict] = []
    for (rule_id, _scope), enforcements in grouped.items():
        if len(enforcements) > 1:
            conflicts.append(
                PolicyConflict(rule_id=rule_id, enforcements=tuple(sorted(enforcements)))
            )
    return conflicts


def simulate_rule(
    *,
    rule: Mapping[str, Any] | PolicyRule,
    past_prs: Sequence[Mapping[str, Any]],
) -> SimulationReport:
    """Replay ``rule`` against ``past_prs`` and return triggered PR numbers."""
    payload = _as_mapping(rule)
    triggered: list[int] = []
    scope = payload.get("scope")
    scope_path = None
    if isinstance(scope, dict):
        scope_path = scope.get("path")
    for pr in past_prs:
        number = int(pr.get("number", 0))
        if pr.get("would_trigger") is True:
            triggered.append(number)
            continue
        paths = pr.get("paths", [])
        if not isinstance(paths, list):
            continue
        if scope_path is None:
            continue
        if any(fnmatch(str(path), str(scope_path)) for path in paths):
            triggered.append(number)
    return SimulationReport(triggered=tuple(triggered))


def write_policy_audit(
    destination: Path,
    *,
    rules: Sequence[Any],
    decisions: Sequence[Any],
) -> PolicyAuditArtifact:
    """Write a JSON audit artifact listing rules and decisions."""
    path = destination / "policy-audit.json" if destination.is_dir() else destination
    payload = {
        "rules": [
            rule if not isinstance(rule, PolicyRule) else rule.model_dump() for rule in rules
        ],
        "decisions": list(decisions),
    }
    path.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return PolicyAuditArtifact(path=path)


def policy_metrics(
    *,
    triggers: int,
    false_positives: int,
    waivers: int,
    blocks: int,
    reviews: int,
) -> PolicyMetrics:
    """Compute trigger, false-positive, waiver, and blocking rates."""
    denominator = float(reviews) if reviews > 0 else 1.0

    def _rate(numerator: int) -> float:
        value = float(numerator) / denominator
        return min(1.0, max(0.0, value))

    return PolicyMetrics(
        trigger_rate=_rate(triggers),
        false_positive_rate=_rate(false_positives),
        waiver_rate=_rate(waivers),
        blocking_rate=_rate(blocks),
    )


__all__ = [
    "PolicyAuditArtifact",
    "PolicyConflict",
    "PolicyMetrics",
    "ScopeContext",
    "SimulationReport",
    "detect_conflicting_policies",
    "parse_rule",
    "policy_metrics",
    "resolve_effective_rules",
    "simulate_rule",
    "write_policy_audit",
]
