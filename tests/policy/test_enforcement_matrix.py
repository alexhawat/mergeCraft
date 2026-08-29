"""GREEN — enforcement mode semantics (AG5 / MCB-12, AG0-G3 choice (a))."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.review_taxonomy import FINDING_SEVERITIES

_ENFORCEMENT_MODES: tuple[str, ...] = ("advisory", "warning", "required", "blocking")
_VIOLATION: dict[str, Any] = {
    "rule_id": "policy.test",
    "severity": "Major",
    "message": "violation",
    "path": "src/api.py",
}


def _evaluate(mode: str, *, severity: str = "Major", rule: dict[str, Any] | None = None) -> Any:
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = dict(_VIOLATION)
    violation["severity"] = severity
    if rule is not None:
        violation["rule"] = rule
    return evaluate_enforcement(mode, violation=violation)


@pytest.mark.parametrize("mode", _ENFORCEMENT_MODES)
@pytest.mark.parametrize("severity", FINDING_SEVERITIES)
def test_mode_by_severity_truth_table(mode: str, severity: str) -> None:
    result = _evaluate(mode, severity=severity)
    assert result.finding is not None
    assert result.finding.severity in FINDING_SEVERITIES


def test_every_mode_pair_is_distinguishable() -> None:
    rule = {"evidence": {"required": ["contract_schema"]}}
    outcomes: dict[str, tuple[bool, str]] = {}
    for mode in _ENFORCEMENT_MODES:
        if mode == "required":
            result = _evaluate(mode, severity="Critical", rule=rule)
        else:
            result = _evaluate(mode, severity="Critical")
        key = (result.contributes_blocker, result.finding.severity if result.finding else "")
        outcomes[mode] = key
    pairs = list(outcomes.items())
    for left_index, (left_mode, left_key) in enumerate(pairs):
        for right_mode, right_key in pairs[left_index + 1 :]:
            if left_key == right_key:
                pytest.fail(f"{left_mode!r} and {right_mode!r} are indistinguishable: {left_key!r}")


def test_every_mode_agrees_with_the_gate() -> None:
    """#554 acceptance: contributes_blocker and decide_approval never disagree."""
    from mergecraft.agents.gates import decide_approval

    rule = {"evidence": {"required": ["contract_schema"]}}
    for mode in _ENFORCEMENT_MODES:
        for severity in FINDING_SEVERITIES:
            result = _evaluate(mode, severity=severity, rule=rule if mode == "required" else None)
            assert result.finding is not None
            conclusion = decide_approval([result.finding], run_succeeded=True, tier="trusted")
            blocked = conclusion == "failure"
            assert blocked is result.contributes_blocker, (
                f"{mode}/{severity}: flag={result.contributes_blocker} gate={conclusion}"
            )


@pytest.mark.parametrize("severity", ["Critical", "Major", "Minor"])
def test_required_without_evidence_keys_preserves_declared_severity(severity: str) -> None:
    result = _evaluate("required", severity=severity, rule={})
    assert result.finding is not None
    assert result.finding.severity == severity


@pytest.mark.parametrize("severity", ["Critical", "Major", "Minor"])
def test_warning_never_reaches_a_blocking_severity(severity: str) -> None:
    """#554: warning is non-blocking by construction, not by an unread flag."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES

    result = _evaluate("warning", severity=severity)
    assert result.finding is not None
    assert result.finding.severity not in BLOCKING_SEVERITIES
    assert result.contributes_blocker is False


def test_blocking_floors_minor_to_a_blocking_severity() -> None:
    """#554: reverses MCB-12 so blocking intent reaches the gate via severity."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES

    result = _evaluate("blocking", severity="Minor")
    assert result.finding is not None
    assert result.finding.severity in BLOCKING_SEVERITIES


def test_required_consults_evidence_when_declared() -> None:
    from mergecraft.policy.evidence import evaluate_rule_evidence

    rule = {
        "id": "public-api.breaking-change-requires-evidence",
        "evidence": {"required": ["contract_schema"]},
        "severity": "Major",
    }
    evidence_outcome = evaluate_rule_evidence(rule, available_evidence={})
    assert evidence_outcome.status == "inconclusive"
    result = _evaluate("required", severity="Major", rule=rule)
    assert result.contributes_blocker or result.finding.severity == "Major"


_EVIDENCE_RULE: dict[str, Any] = {"evidence": {"required": ["contract_schema"]}}


def _evaluate_required(*, severity: str, available: dict[str, Any]) -> Any:
    from mergecraft.policy.enforcement import evaluate_enforcement

    violation = dict(_VIOLATION)
    violation["severity"] = severity
    violation["rule"] = _EVIDENCE_RULE
    violation["available_evidence"] = available
    return evaluate_enforcement("required", violation=violation)


@pytest.mark.parametrize("severity", ["Critical", "Major", "Minor", "Trivial"])
def test_required_blocks_at_every_declared_severity_while_evidence_is_missing(
    severity: str,
) -> None:
    """#554 follow-up: a low declared severity must not let an obligation pass.

    ``required`` is documented to block until evidence is present, and the
    schema permits ``Minor`` and ``Trivial``. Deriving the flag from severity
    alone left those two below the gate, so the obligation silently cleared.
    """
    from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval

    result = _evaluate_required(severity=severity, available={})

    assert result.finding is not None
    assert result.finding.severity in BLOCKING_SEVERITIES
    assert result.contributes_blocker is True
    assert decide_approval([result.finding], run_succeeded=True, tier="trusted") == "failure"


@pytest.mark.parametrize("severity", ["Critical", "Major", "Minor", "Trivial"])
def test_required_stops_blocking_once_evidence_is_satisfied(severity: str) -> None:
    """A cleared obligation must not block, at any declared severity."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval

    result = _evaluate_required(
        severity=severity,
        available={"contract_schema": "docs/api.yaml"},
    )

    assert result.finding is not None
    assert result.finding.severity not in BLOCKING_SEVERITIES
    assert result.contributes_blocker is False
    assert decide_approval([result.finding], run_succeeded=True, tier="trusted") == "success"
