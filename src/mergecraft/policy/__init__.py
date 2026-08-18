"""Policy-as-code — schema-validated rules, scoping, and enforcement (DG5)."""

from __future__ import annotations

from mergecraft.policy.enforcement import EnforcementMode, EnforcementResult, evaluate_enforcement
from mergecraft.policy.evidence import EvidenceOutcome, evaluate_rule_evidence
from mergecraft.policy.exceptions import PolicyException, exception_applies, parse_exception
from mergecraft.policy.schema import PolicyConfigError, PolicyRule, parse_rule, parse_rules_document
from mergecraft.policy.scoping import EffectiveRule, ScopeContext, resolve_effective_rules

__all__ = [
    "EffectiveRule",
    "EnforcementMode",
    "EnforcementResult",
    "EvidenceOutcome",
    "PolicyConfigError",
    "PolicyException",
    "PolicyRule",
    "ScopeContext",
    "evaluate_enforcement",
    "evaluate_rule_evidence",
    "exception_applies",
    "parse_exception",
    "parse_rule",
    "parse_rules_document",
    "resolve_effective_rules",
]
