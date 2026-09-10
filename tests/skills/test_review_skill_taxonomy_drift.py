"""RS1.5 — taxonomy drift gates against code constants (RS4, D8)."""

from __future__ import annotations

import copy

import pytest

from mergecraft.findings.severity import BLOCKING_SEVERITIES
from mergecraft.review_taxonomy import (
    FINDING_CATEGORIES,
    FINDING_CONFIDENCES,
    FINDING_EFFORTS,
    FINDING_SEVERITIES,
    WITHDRAWN_FINDINGS_HEADING,
)


def _skill_text() -> str:
    from tests.context.review_skill_support import skill_root

    root = skill_root()
    parts = [root / "SKILL.md"]
    refs = root / "references"
    if refs.is_dir():
        parts.extend(sorted(refs.glob("*.md")))
    return "\n".join(path.read_text(encoding="utf-8") for path in parts)


@pytest.mark.xfail(reason="green after RS3: category naming in skill", strict=False)
def test_skill_names_every_finding_category() -> None:
    text = _skill_text()
    for category in FINDING_CATEGORIES:
        assert category in text


@pytest.mark.xfail(reason="green after RS3: severity/effort/confidence naming", strict=False)
def test_skill_names_every_severity_effort_and_confidence() -> None:
    text = _skill_text()
    for value in (*FINDING_SEVERITIES, *FINDING_EFFORTS, *FINDING_CONFIDENCES):
        assert value in text


@pytest.mark.xfail(reason="green after RS3: blocking severity naming", strict=False)
def test_skill_names_every_blocking_severity() -> None:
    text = _skill_text()
    for severity in sorted(BLOCKING_SEVERITIES):
        assert severity in text


@pytest.mark.xfail(reason="green after RS3: withdrawn-findings heading", strict=False)
def test_skill_names_the_withdrawn_findings_heading() -> None:
    assert WITHDRAWN_FINDINGS_HEADING in _skill_text()


@pytest.mark.xfail(reason="green after RS4: taxonomy drift meta-gate", strict=False)
def test_gate_fails_when_a_taxonomy_value_is_added() -> None:
    from mergecraft.evals.skill_taxonomy_gate import taxonomy_values_covered_by_skill

    baseline = taxonomy_values_covered_by_skill()
    assert baseline.missing == []

    mutated = copy.deepcopy(baseline.taxonomy)
    mutated["FINDING_CATEGORIES"] = (*mutated["FINDING_CATEGORIES"], "Synthetic Drift Category")
    drift = taxonomy_values_covered_by_skill(taxonomy=mutated)
    assert drift.missing == ["Synthetic Drift Category"]
