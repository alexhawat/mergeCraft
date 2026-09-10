"""Impact-based severity: matched-paraphrase pairs (RA1.2, D15).

Each case runs the *same asserted impact* twice through the real composition —
``infer_category_from_message`` then ``apply_severity_rubric`` — once with an
incidental word and once without. The claim is that the pair agrees. A single
assertion on one member would pass on a vocabulary change that merely moves
which word demotes the finding (N4/N20).

Every incidental case is expected to fail until RA3 lands: incidentals must not
lower a severity across a blocking boundary.
"""

from __future__ import annotations

from typing import Any

from tests.findings.fixtures.severity_pairs import SEVERITY_PAIRS, SeverityPair
from tests.findings.support import make_finding


def _by_case(case_id: str) -> SeverityPair:
    for pair in SEVERITY_PAIRS:
        if pair.case_id == case_id:
            return pair
    msg = f"unknown severity pair: {case_id}"
    raise KeyError(msg)


def _normalized(message: str, severity: str) -> Any:
    """Drive inference -> cap over one message and return the normalized finding."""
    from mergecraft.findings.severity_rubric import (
        apply_severity_rubric,
        infer_category_from_message,
    )

    category = infer_category_from_message(message)
    finding = make_finding(
        category=category,
        severity=severity,
        message=message,
        path="src/session.py",
        start_line=12,
        end_line=12,
        source="agent",
    )
    return apply_severity_rubric(finding, model_assigned_severity=severity)


def _assert_pair_agrees(pair: SeverityPair) -> None:
    incidental = _normalized(pair.incidental_message, pair.asserted_severity)
    control = _normalized(pair.impact_message, pair.asserted_severity)
    assert incidental.severity == control.severity, (
        f"{pair.case_id}: incidental prose changed the severity "
        f"({incidental.severity!r} vs control {control.severity!r})"
    )
    assert control.severity == pair.asserted_severity, (
        f"{pair.case_id}: control lost its asserted severity "
        f"({control.severity!r} != {pair.asserted_severity!r})"
    )


def test_critical_security_survives_incidental_readme() -> None:
    _assert_pair_agrees(_by_case("critical-security-readme"))


def test_critical_security_survives_incidental_comment() -> None:
    _assert_pair_agrees(_by_case("critical-security-comment"))


def test_critical_security_survives_incidental_style() -> None:
    _assert_pair_agrees(_by_case("critical-security-style"))


def test_critical_security_survives_incidental_naming() -> None:
    _assert_pair_agrees(_by_case("critical-security-naming"))


def test_critical_security_survives_incidental_typo() -> None:
    _assert_pair_agrees(_by_case("critical-security-typo"))


def test_major_correctness_survives_incidental_comment() -> None:
    _assert_pair_agrees(_by_case("major-correctness-comment"))


def test_control_paraphrases_retain_their_asserted_severity() -> None:
    """Every control keeps its asserted severity — the no-incidental guard."""
    for pair in SEVERITY_PAIRS:
        control = _normalized(pair.impact_message, pair.asserted_severity)
        assert control.severity == pair.asserted_severity, (
            f"{pair.case_id}: control was capped without an incidental word"
        )
