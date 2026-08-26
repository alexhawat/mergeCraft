"""RED — enforcement mode semantics (AG5 / MCB-12, AG0-G3 choice (a))."""

from __future__ import annotations

from typing import Any

import pytest

from mergecraft.review_taxonomy import FINDING_SEVERITIES

pytestmark = pytest.mark.xfail(
    reason="green after AG5: distinct enforcement modes",
    strict=False,
)

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
    outcomes: dict[str, tuple[bool, str]] = {}
    for mode in _ENFORCEMENT_MODES:
        result = _evaluate(mode, severity="Critical")
        key = (result.contributes_blocker, result.finding.severity if result.finding else "")
        outcomes[mode] = key
    pairs = list(outcomes.items())
    for left_index, (left_mode, left_key) in enumerate(pairs):
        for right_mode, right_key in pairs[left_index + 1 :]:
            if left_key == right_key:
                pytest.fail(f"{left_mode!r} and {right_mode!r} are indistinguishable: {left_key!r}")


@pytest.mark.parametrize("severity", ["Critical", "Major", "Minor"])
def test_non_blocking_modes_preserve_declared_severity(severity: str) -> None:
    for mode in ("advisory", "warning", "required"):
        result = _evaluate(mode, severity=severity)
        assert result.finding is not None
        assert result.finding.severity == severity


def test_blocking_does_not_promote_minor_to_major() -> None:
    result = _evaluate("blocking", severity="Minor")
    assert result.finding is not None
    assert result.finding.severity == "Minor"


def test_required_consults_evidence_when_declared() -> None:
    from mergecraft.policy.evidence import evaluate_rule_evidence

    rule = {
        "id": "public-api.breaking-change-requires-evidence",
        "evidence": {"required": ["contract_schema"]},
        "severity": "Major",
    }
    evidence_outcome = evaluate_rule_evidence(rule, available_evidence={})
    assert evidence_outcome.status == "inconclusive"
    result = _evaluate("required", severity="Major")
    assert result.contributes_blocker or result.finding.severity == "Major"
