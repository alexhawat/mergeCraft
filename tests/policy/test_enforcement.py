"""DG5 policy enforcement modes mapped onto the existing gate (D7).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — advisory/warning/required/blocking enforcement.
"""

from __future__ import annotations

from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval


def test_advisory_warning_required_blocking_modes() -> None:
    """Four enforcement modes produce distinct gate-facing outcomes."""
    from mergecraft.policy.enforcement import EnforcementMode, evaluate_enforcement

    violation = {"rule_id": "sample", "path": "src/app.py", "message": "policy violation"}

    advisory = evaluate_enforcement(mode="advisory", violation=violation)
    warning = evaluate_enforcement(mode="warning", violation=violation)
    required = evaluate_enforcement(mode="required", violation=violation)
    blocking = evaluate_enforcement(mode="blocking", violation=violation)

    assert advisory.contributes_blocker is False
    assert warning.contributes_blocker is False
    assert required.contributes_blocker is False
    assert blocking.contributes_blocker is True
    assert advisory.finding is not None
    assert warning.finding is not None
    assert required.finding is not None
    assert blocking.finding is not None
    assert blocking.finding.severity in BLOCKING_SEVERITIES

    modes: tuple[EnforcementMode, ...] = ("advisory", "warning", "required", "blocking")
    assert advisory.mode in modes
    assert blocking.mode in modes


def test_non_blocking_modes_preserve_declared_severity() -> None:
    """Advisory violations keep the rule severity instead of coercing to Major."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "style-nit",
        "path": "src/app.py",
        "message": "policy violation",
        "severity": "Minor",
    }
    result = evaluate_enforcement(mode="advisory", violation=violation)

    assert result.finding is not None
    assert result.finding.severity == "Minor"
    assert result.contributes_blocker is False


def test_blocking_rule_contributes_a_blocking_finding_not_a_second_gate() -> None:
    """Blocking policy violations feed ``decide_approval`` — no parallel approval path."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "no-hardcoded-secrets",
        "path": "src/config.py",
        "message": "token",
        "severity": "Minor",
    }
    result = evaluate_enforcement(mode="blocking", violation=violation)

    assert result.finding is not None
    assert result.finding.severity in BLOCKING_SEVERITIES
    findings = [result.finding]
    conclusion = decide_approval(findings, run_succeeded=True, tier="trusted")

    assert conclusion == "failure"
    assert not hasattr(evaluate_enforcement, "decide_policy_approval")


def test_blocking_mode_promotes_minor_declared_severity_to_gate_blocker() -> None:
    """D7: enforcement mode — not declared severity alone — controls merge blocking."""
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
    assert result.finding.severity in BLOCKING_SEVERITIES
    assert decide_approval([result.finding], run_succeeded=True, tier="trusted") == "failure"


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
