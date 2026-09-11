"""Impact-based severity: matched-paraphrase pairs (RA1.2, D15).

Each case runs the *same asserted impact* twice through the real composition —
``infer_category_from_message`` then ``apply_severity_rubric`` — once with an
incidental word and once without. The claim is that the pair agrees. A single
assertion on one member would pass on a vocabulary change that merely moves
which word demotes the finding (N4/N20).

Incidental prose must not lower a severity across a blocking boundary; RA3 has
landed, so these cases pin the enforced contract as ordinary passing tests.
"""

from __future__ import annotations

from typing import Any

import pytest

from tests.findings.fixtures.severity_pairs import (
    AUTHOR_FAMILY_PAIRS,
    SEVERITY_PAIRS,
    AuthorFamilyPair,
    SeverityPair,
)
from tests.findings.support import make_finding


def _by_case(case_id: str) -> SeverityPair:
    for pair in SEVERITY_PAIRS:
        if pair.case_id == case_id:
            return pair
    msg = f"unknown severity pair: {case_id}"
    raise KeyError(msg)


def _author_pair(case_id: str) -> AuthorFamilyPair:
    for pair in AUTHOR_FAMILY_PAIRS:
        if pair.case_id == case_id:
            return pair
    msg = f"unknown author-family pair: {case_id}"
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


# ---------------------------------------------------------------------------
# Author-family pairs (RA3 regression): prose that begins with ``auth`` is not a
# security signal, so it must not lift a style/docs finding across a blocking
# boundary — and it must not lower a genuine correctness impact.
# ---------------------------------------------------------------------------


def _assert_author_pair_agrees(pair: AuthorFamilyPair) -> tuple[Any, Any]:
    incidental = _normalized(pair.incidental_message, pair.asserted_severity)
    control = _normalized(pair.control_message, pair.asserted_severity)
    assert incidental.severity == control.severity, (
        f"{pair.case_id}: author-family prose changed the severity "
        f"({incidental.severity!r} vs control {control.severity!r})"
    )
    return incidental, control


@pytest.mark.parametrize("case_id", [pair.case_id for pair in AUTHOR_FAMILY_PAIRS])
def test_author_family_pair_agrees_on_severity(case_id: str) -> None:
    _assert_author_pair_agrees(_author_pair(case_id))


def test_style_nit_with_authors_tail_is_not_raised_to_blocking() -> None:
    """An incidental ``authors`` must not keep a style nit at a blocking grade."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval

    pair = _author_pair("critical-style-authors-tail")
    incidental, control = _assert_author_pair_agrees(pair)

    assert control.severity not in BLOCKING_SEVERITIES
    assert incidental.severity not in BLOCKING_SEVERITIES, (
        f"incidental 'authors' lifted a style nit to {incidental.severity!r}"
    )
    assert decide_approval([incidental], run_succeeded=True, tier="trusted") == "success", (
        "an incidental author-family word blocked approval of a style nit"
    )


def test_style_nit_with_authorship_in_the_core_is_not_raised_to_blocking() -> None:
    """The author word in the asserted impact itself must not read as security."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES

    pair = _author_pair("critical-style-authorship-core")
    incidental, control = _assert_author_pair_agrees(pair)

    assert control.severity not in BLOCKING_SEVERITIES
    assert incidental.severity not in BLOCKING_SEVERITIES, (
        f"'authorship' in the core lifted a style nit to {incidental.severity!r}"
    )


def test_docs_nit_with_authoritative_tail_is_not_raised_to_blocking() -> None:
    """An incidental ``authoritative`` must not keep a docs nit at a blocking grade."""
    from mergecraft.agents.gates import BLOCKING_SEVERITIES, decide_approval

    pair = _author_pair("critical-docs-authoritative-tail")
    incidental, control = _assert_author_pair_agrees(pair)

    assert control.severity not in BLOCKING_SEVERITIES
    assert incidental.severity not in BLOCKING_SEVERITIES, (
        f"incidental 'authoritative' lifted a docs nit to {incidental.severity!r}"
    )
    assert decide_approval([incidental], run_succeeded=True, tier="trusted") == "success", (
        "an incidental author-family word blocked approval of a docs nit"
    )


def test_correctness_impact_keeps_its_asserted_severity_with_an_authors_tail() -> None:
    """An author-family word must not lower a genuine correctness impact either."""
    pair = _author_pair("critical-correctness-authors-tail")
    incidental, control = _assert_author_pair_agrees(pair)

    assert control.severity == pair.asserted_severity
    assert incidental.severity == pair.asserted_severity
