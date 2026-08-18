"""DG5 policy scoping — deterministic resolution and inheritance (G11).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — org/repo/branch/path/language scope resolution.
"""

from __future__ import annotations

import pytest

from tests.policy.conftest import ORG_RULE_YAML, PATH_RULE_YAML, REPO_RULE_YAML


@pytest.mark.xfail(reason="green after DG5.2", strict=False)
def test_org_repo_branch_path_language_scopes_resolve_deterministically() -> None:
    """The same scope inputs always yield the same effective rule ordering."""
    from mergecraft.policy.schema import parse_rule
    from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

    rules = [
        parse_rule(ORG_RULE_YAML),
        parse_rule(REPO_RULE_YAML),
        parse_rule(PATH_RULE_YAML),
    ]
    context = ScopeContext(
        org="acme-corp",
        repo="payments-api",
        branch="feature/token-rotation",
        path="src/handlers/pay.py",
        language="python",
    )

    first = resolve_effective_rules(rules, context=context)
    second = resolve_effective_rules(rules, context=context)

    assert [rule.id for rule in first] == [rule.id for rule in second]
    assert {rule.id for rule in first} >= {"org-baseline", "repo-override", "path-specific"}


@pytest.mark.xfail(reason="green after DG5.2", strict=False)
def test_inheritance_org_then_repo_then_path() -> None:
    """Org baseline applies first; repo and path layers override in order."""
    from mergecraft.policy.schema import parse_rule
    from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

    rules = [
        parse_rule(ORG_RULE_YAML),
        parse_rule(REPO_RULE_YAML),
        parse_rule(PATH_RULE_YAML),
    ]
    context = ScopeContext(
        org="acme-corp",
        repo="payments-api",
        branch="main",
        path="src/handlers/pay.py",
        language="python",
    )

    effective = resolve_effective_rules(rules, context=context)
    layers = [entry.source_layer for entry in effective]

    assert layers.index("org") < layers.index("repo") < layers.index("path")
    path_rule = next(entry for entry in effective if entry.rule.id == "path-specific")
    assert path_rule.rule.enforcement == "blocking"
