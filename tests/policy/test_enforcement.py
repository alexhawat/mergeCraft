"""DG5 policy enforcement modes mapped onto the existing gate (D7).

Wave plan: ``.ignorelocal/waves/05-review-depth-governance-wave-plan.md`` (PR DG5).
Implementation: **DG5.2** — advisory/warning/required/blocking enforcement.
"""

from __future__ import annotations

import pytest

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


# --- Enforcement mode vs. the gate it feeds -------------------------------
#
# ``EnforcementResult.contributes_blocker`` records what a mode *means*, and
# ``decide_approval`` decides from ``Finding.severity``. Nothing reads the
# flag: it appears nowhere in ``src`` outside ``policy/enforcement.py``, and
# ``evaluate_enforcement`` has no production caller, so no policy violation
# reaches the gate by any path today. The two representations therefore
# disagree in two cells without any runtime consequence yet.
#
# These pin the disagreement rather than assert a resolution, because the
# resolution is a design fork (see the follow-up issue): either the gate
# learns about the flag, or severity becomes authoritative and the modes cap
# and floor accordingly. Both cells flip to green under either branch, so
# ``strict=True`` — an xpass means the fork was taken and these become real
# assertions rather than quietly passing pins.


@pytest.mark.xfail(
    strict=True,
    reason="blocking + Minor sets contributes_blocker=True, but the gate reads "
    "severity and Minor is not blocking. MCB-12 removed the Minor->Major "
    "promotion that used to make this block; the intent moved to a flag "
    "nothing consumes.",
)
def test_blocking_mode_blocks_even_at_minor_severity() -> None:
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "no-hardcoded-secrets",
        "path": "src/config.py",
        "message": "token",
        "severity": "Minor",
    }
    result = evaluate_enforcement(mode="blocking", violation=violation)
    assert result.contributes_blocker is True
    assert result.finding is not None

    conclusion = decide_approval([result.finding], run_succeeded=True, tier="trusted")
    assert conclusion == "failure", (
        "a blocking rule that contributes a blocker must block the gate it feeds"
    )


@pytest.mark.xfail(
    strict=True,
    reason="warning + Major sets contributes_blocker=False, but the declared "
    "severity is preserved and the gate blocks on it. 'warning never blocks' "
    "and 'warning preserves declared severity' cannot both hold while the "
    "gate decides from severity.",
)
def test_warning_mode_does_not_block_at_major_severity() -> None:
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = {
        "rule_id": "prefer-structured-logging",
        "path": "src/app.py",
        "message": "print()",
        "severity": "Major",
    }
    result = evaluate_enforcement(mode="warning", violation=violation)
    assert result.contributes_blocker is False
    assert result.finding is not None

    conclusion = decide_approval([result.finding], run_succeeded=True, tier="trusted")
    assert conclusion != "failure", (
        "a warning rule that contributes no blocker must not block the gate it feeds"
    )
