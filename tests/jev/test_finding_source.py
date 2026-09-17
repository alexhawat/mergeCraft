"""D3 — FindingSource gains exactly ``classifier``; confidence stays ordinal."""

from __future__ import annotations

from typing import get_args

import pytest

from mergecraft.analyzers.finding import Finding, FindingValidationError, make_finding
from mergecraft.review_taxonomy import FINDING_CONFIDENCES, FindingSource


def test_finding_confidence_stays_three_value_ordinal() -> None:
    assert FINDING_CONFIDENCES == ("certain", "likely", "possible")
    assert "0.9" not in FINDING_CONFIDENCES


def test_finding_has_no_raw_float_confidence_field() -> None:
    fields = set(Finding.model_fields)
    assert "confidence_float" not in fields
    assert "raw_confidence" not in fields
    assert "noul" not in fields


def test_finding_source_gains_exactly_classifier() -> None:
    assert get_args(FindingSource) == (
        "analyzer",
        "agent",
        "ci",
        "trajectory",
        "classifier",
    )


def test_make_finding_accepts_classifier_source() -> None:
    finding = make_finding(
        tool="jev",
        rule_id="unit/v1",
        category="Security & Privacy",
        severity="Major",
        confidence="certain",
        message="setpriv drop without HOME redirect",
        path="src/mergecraft/utils/privilege.py",
        start_line=12,
        end_line=12,
        source="classifier",
        evidence=["@@ wrap_agent_command @@"],
    )
    assert finding.source == "classifier"
    assert finding.confidence == "certain"
    assert 0.92 not in finding.evidence
    assert "0.92" not in finding.evidence


def test_classifier_source_still_rejects_float_confidence() -> None:
    with pytest.raises(FindingValidationError):
        make_finding(
            tool="jev",
            rule_id="unit/v1",
            category="Security & Privacy",
            severity="Major",
            confidence="0.92",
            message="float confidence is not an ordinal",
            path="src/mergecraft/utils/privilege.py",
            start_line=12,
            end_line=12,
            source="classifier",
        )
