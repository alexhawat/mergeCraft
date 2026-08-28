"""DG5 policy enforcement modes mapped onto the existing gate (D7).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — advisory/warning/required/blocking enforcement.
"""

from __future__ import annotations

from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval


def test_blocking_rule_contributes_a_blocking_finding_not_a_second_gate() -> None:
    """Blocking policy violations feed ``decide_approval`` — no parallel approval path."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "no-hardcoded-secrets",
        "path": "src/config.py",
        "message": "token",
        "severity": "Major",
    }
    result = evaluate_enforcement(mode="blocking", violation=violation)

    assert result.finding is not None
    assert result.finding.severity in BLOCKING_SEVERITIES
    findings = [result.finding]
    conclusion = decide_approval(findings, run_succeeded=True, tier="trusted")

    assert conclusion == "failure"
    assert not hasattr(evaluate_enforcement, "decide_policy_approval")


def test_blocking_mode_preserves_minor_declared_severity() -> None:
    """D12: blocking keeps a declared ``Minor`` finding at ``Minor``."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "style-block",
        "path": "src/app.py",
        "message": "policy violation",
        "severity": "Minor",
    }
    result = evaluate_enforcement(mode="blocking", violation=violation)

    assert result.contributes_blocker is True
    assert result.finding is not None
    assert result.finding.severity == "Minor"


def test_advisory_mode_caps_critical_declared_severity_to_non_blocker() -> None:
    """D7: advisory rules must not block merges via inflated declared severity."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "docs-nit",
        "path": "README.md",
        "message": "policy violation",
        "severity": "Critical",
    }
    result = evaluate_enforcement(mode="advisory", violation=violation)

    assert result.contributes_blocker is False
    assert result.finding is not None
    assert result.finding.severity not in BLOCKING_SEVERITIES
    assert decide_approval([result.finding], run_succeeded=True, tier="trusted") == "success"
