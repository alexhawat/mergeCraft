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


def test_blocking_minor_blocks_at_the_gate() -> None:
    """#554: a blocking rule must block, so declared ``Minor`` is floored to ``Major``.

    This deliberately reverses MCB-12's "blocking no longer promotes Minor".
    That change left the blocking intent in ``contributes_blocker``, which
    ``decide_approval`` never reads, so a blocking rule silently passed.
    """
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
    assert result.finding.severity == "Major"
    assert decide_approval([result.finding], run_succeeded=True, tier="trusted") == "failure"


def test_blocking_minor_keeps_the_declared_severity_visible() -> None:
    """Flooring must not hide what the rule actually declared."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "style-block",
        "path": "src/app.py",
        "message": "policy violation",
        "severity": "Minor",
    }
    result = evaluate_enforcement(mode="blocking", violation=violation)

    assert result.finding is not None
    assert any("Minor" in item for item in result.finding.evidence)


def test_warning_major_does_not_block_at_the_gate() -> None:
    """#554: warning never blocks, so a declared blocking severity is capped."""
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "style-warn",
        "path": "src/app.py",
        "message": "policy violation",
        "severity": "Major",
    }
    result = evaluate_enforcement(mode="warning", violation=violation)

    assert result.contributes_blocker is False
    assert result.finding is not None
    assert result.finding.severity not in BLOCKING_SEVERITIES
    assert decide_approval([result.finding], run_succeeded=True, tier="trusted") == "success"
    assert any("Major" in item for item in result.finding.evidence)


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
