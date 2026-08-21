"""Policy scope resolution — deterministic inheritance org → repo → path → symbol."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from typing import Literal

from mergecraft.policy.schema import PolicyRule, RuleScope  # noqa: TC001

SourceLayer = Literal["org", "repo", "path", "symbol", "global"]

_LAYER_ORDER: dict[SourceLayer, int] = {
    "global": 0,
    "org": 1,
    "repo": 2,
    "path": 3,
    "symbol": 4,
}


@dataclass(frozen=True, slots=True)
class ScopeContext:
    """Runtime scope inputs for policy resolution."""

    org: str
    repo: str
    branch: str
    path: str
    language: str
    symbol: str | None = None


@dataclass(frozen=True, slots=True)
class EffectiveRule:
    """A rule that applies in the current scope, with its source layer."""

    rule: PolicyRule
    source_layer: SourceLayer

    @property
    def id(self) -> str:
        """Stable rule id — convenience alias for ``rule.id``."""
        return self.rule.id


def _source_layer(scope: RuleScope | None) -> SourceLayer:
    if scope is None:
        return "global"
    if scope.symbol is not None:
        return "symbol"
    if scope.path is not None:
        return "path"
    if scope.repo is not None:
        return "repo"
    if scope.org is not None:
        return "org"
    return "global"


def _scope_matches(scope: RuleScope | None, context: ScopeContext) -> bool:
    if scope is None:
        return True
    if scope.org is not None and scope.org != context.org:
        return False
    if scope.repo is not None and scope.repo != context.repo:
        return False
    if scope.branch is not None and scope.branch != context.branch:
        return False
    if scope.language is not None and scope.language != context.language:
        return False
    if scope.path is not None and not fnmatch.fnmatch(context.path, scope.path):
        return False
    if scope.symbol is None:
        return True
    if context.symbol is None:
        return False
    return fnmatch.fnmatch(context.symbol, scope.symbol)


def resolve_effective_rules(
    rules: list[PolicyRule],
    *,
    context: ScopeContext,
) -> list[EffectiveRule]:
    """Return rules whose scope matches ``context``, ordered by inheritance depth.

    When multiple rules share the same ``id``, the deepest matching scope wins
    (org → repo → path → symbol).
    """
    effective = [
        EffectiveRule(rule=rule, source_layer=_source_layer(rule.scope))
        for rule in rules
        if _scope_matches(rule.scope, context)
    ]
    by_id: dict[str, EffectiveRule] = {}
    for entry in effective:
        existing = by_id.get(entry.rule.id)
        if (
            existing is None
            or _LAYER_ORDER[entry.source_layer] > _LAYER_ORDER[existing.source_layer]
        ):
            by_id[entry.rule.id] = entry
    return sorted(
        by_id.values(),
        key=lambda entry: (_LAYER_ORDER[entry.source_layer], entry.rule.id),
    )


__all__ = [
    "EffectiveRule",
    "ScopeContext",
    "SourceLayer",
    "resolve_effective_rules",
]
