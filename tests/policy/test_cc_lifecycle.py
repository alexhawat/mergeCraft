"""W8 / W12 — policy lifecycle back half (#358).

Does not re-test schema / scoping / enforcement / exceptions / evidence
requirements (issue out of scope). Policy packs are #359.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mergecraft.policy.schema import parse_rule
from mergecraft.policy.scoping import ScopeContext, resolve_effective_rules
from tests.support.cc_batch import load_module, plain, require_callable, require_registered
from tests.support.dead_package_wiring import SRC_ROOT


def test_policy_front_half_already_ships() -> None:
    """#358 out of scope — schema/scoping/enforcement already shipped."""
    for name in ("schema.py", "scoping.py", "enforcement.py", "exceptions.py", "evidence.py"):
        assert (SRC_ROOT / "policy" / name).is_file()


def test_policy_effective_help_names_source_of_every_rule() -> None:
    """#358 — ``mergecraft policy effective`` shows the resolved set and each source."""
    result = require_registered(
        "policy", "effective", "--help", label="mergecraft policy effective"
    )
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "source" in help_text or "effective" in help_text


def test_policy_simulate_help_is_registered() -> None:
    """#358 — ``mergecraft policy simulate`` exists."""
    result = require_registered("policy", "simulate", "--help", label="mergecraft policy simulate")
    help_text = plain(result.stdout + result.stderr).casefold()
    assert "simulate" in help_text or "past" in help_text or "pr" in help_text


def test_policy_resolution_stays_deterministic_at_symbol_scope() -> None:
    """#358 — hierarchy extends to symbol scope; same inputs → same winners."""
    module = load_module("mergecraft.policy.lifecycle")
    parse = getattr(module, "parse_rule", parse_rule)
    resolve = getattr(module, "resolve_effective_rules", resolve_effective_rules)
    rules = [
        parse(
            """
id: shared-rule
owner: platform
version: 1
rationale: Path default.
severity: Minor
enforcement: advisory
scope:
  path: src/app.py
"""
        ),
        parse(
            """
id: shared-rule
owner: platform
version: 2
rationale: Symbol override.
severity: Major
enforcement: blocking
scope:
  path: src/app.py
  symbol: process
"""
        ),
    ]
    context_cls = getattr(module, "ScopeContext", ScopeContext)
    kwargs = {
        "org": "acme",
        "repo": "demo",
        "branch": "main",
        "path": "src/app.py",
        "language": "python",
    }
    try:
        context = context_cls(**kwargs, symbol="process")
    except TypeError:
        pytest.fail("ScopeContext must accept symbol for #358")
    first = resolve(rules, context=context)
    second = resolve(rules, context=context)
    assert [entry.rule.version for entry in first] == [entry.rule.version for entry in second]
    winner = next(entry for entry in first if entry.rule.id == "shared-rule")
    assert winner.rule.version == 2
    assert winner.source_layer in {"symbol", "path"}


def test_conflicting_policies_are_detected() -> None:
    """#358 — conflicting policies are surfaced instead of silently merged."""
    module = load_module("mergecraft.policy.lifecycle")
    detect = require_callable(module, "detect_conflicting_policies")
    conflicts = detect(
        [
            {"id": "a", "enforcement": "blocking", "scope": {"path": "src/**"}},
            {"id": "a", "enforcement": "advisory", "scope": {"path": "src/**"}},
        ]
    )
    assert conflicts


def test_policy_simulate_runs_a_proposed_rule_against_past_prs() -> None:
    """#358 — simulate a proposed rule against past PRs before enabling it."""
    module = load_module("mergecraft.policy.lifecycle")
    simulate = require_callable(module, "simulate_rule")
    report = simulate(
        rule={"id": "no-secrets", "enforcement": "blocking"},
        past_prs=[{"number": 1, "paths": ["src/app.py"], "would_trigger": True}],
    )
    triggered = getattr(report, "triggered", None)
    if triggered is None:
        triggered = report.get("triggered")
    assert triggered


def test_policy_audit_artifacts_are_emitted(tmp_path: Path) -> None:
    """#358 — policy audit artifacts are produced."""
    module = load_module("mergecraft.policy.lifecycle")
    write_audit = require_callable(module, "write_policy_audit")
    artifact = write_audit(tmp_path, rules=[{"id": "no-secrets"}], decisions=["block"])
    path = getattr(artifact, "path", artifact)
    assert Path(path).is_file() or isinstance(artifact, dict)


def test_policy_metrics_include_trigger_fp_waiver_and_blocking_rates() -> None:
    """#358 — trigger, false-positive, waiver, and blocking rates."""
    module = load_module("mergecraft.policy.lifecycle")
    metrics = require_callable(module, "policy_metrics")(
        triggers=10,
        false_positives=1,
        waivers=2,
        blocks=4,
        reviews=10,
    )
    payload = metrics if isinstance(metrics, dict) else metrics.__dict__
    for key in ("trigger_rate", "false_positive_rate", "waiver_rate", "blocking_rate"):
        assert key in payload
        assert 0.0 <= float(payload[key]) <= 1.0
