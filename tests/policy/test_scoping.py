"""DG5 policy scoping — deterministic resolution and inheritance (G11).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — org/repo/branch/path/language scope resolution.
"""

from __future__ import annotations

from tests.policy.conftest import ORG_RULE_YAML, PATH_RULE_YAML, REPO_RULE_YAML


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


def test_deeper_scope_overrides_same_id_at_shallower_layer() -> None:
    """Path-scoped rules supersede org/repo rules that share the same id."""
    from mergecraft.policy.schema import parse_rule
    from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

    org_rule = parse_rule(
        """
id: shared-rule
owner: org-platform
version: 1
rationale: Org default.
severity: Minor
enforcement: advisory
scope:
  org: acme-corp
"""
    )
    path_rule = parse_rule(
        """
id: shared-rule
owner: team-alpha
version: 2
rationale: Path override.
severity: Critical
enforcement: blocking
scope:
  org: acme-corp
  repo: payments-api
  path: "src/handlers/**"
"""
    )
    context = ScopeContext(
        org="acme-corp",
        repo="payments-api",
        branch="main",
        path="src/handlers/pay.py",
        language="python",
    )

    effective = resolve_effective_rules([org_rule, path_rule], context=context)

    assert len(effective) == 1
    assert effective[0].rule.id == "shared-rule"
    assert effective[0].source_layer == "path"
    assert effective[0].rule.enforcement == "blocking"


def test_branch_mismatch_excludes_scoped_rule() -> None:
    """A rule scoped to ``branch: main`` must not apply on ``feature/foo`` (D5)."""
    from mergecraft.policy.schema import parse_rule
    from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

    rule = parse_rule(
        """
id: main-only
owner: platform
version: 1
rationale: Main branch guardrail.
severity: Major
enforcement: blocking
scope:
  org: acme-corp
  repo: payments-api
  branch: main
"""
    )
    context = ScopeContext(
        org="acme-corp",
        repo="payments-api",
        branch="feature/token-rotation",
        path="src/handlers/pay.py",
        language="python",
    )

    effective = resolve_effective_rules([rule], context=context)

    assert effective == []


def test_language_mismatch_excludes_scoped_rule() -> None:
    """A rule scoped to ``language: python`` must not apply to ``typescript`` files (D5)."""
    from mergecraft.policy.schema import parse_rule
    from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules

    rule = parse_rule(
        """
id: python-only
owner: platform
version: 1
rationale: Python-only lint policy.
severity: Minor
enforcement: advisory
scope:
  org: acme-corp
  repo: payments-api
  language: python
"""
    )
    context = ScopeContext(
        org="acme-corp",
        repo="payments-api",
        branch="main",
        path="src/handlers/pay.ts",
        language="typescript",
    )

    effective = resolve_effective_rules([rule], context=context)

    assert effective == []
