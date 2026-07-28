"""Normalized ``Finding`` schema (D2, D12)."""

from __future__ import annotations

import pytest

from mergecraft.review_taxonomy import (
    FINDING_CATEGORIES,
    FINDING_EFFORTS,
    finding_fingerprint,
)
from tests.analyzers.support import import_module

pytestmark = pytest.mark.xfail(reason="green after W2: Finding schema", strict=False)


def test_finding_requires_taxonomy_category_and_severity() -> None:
    finding_mod = import_module("mergecraft.analyzers.finding")
    with pytest.raises(finding_mod.FindingValidationError, match=r"category|severity"):
        finding_mod.Finding(
            tool="actionlint",
            rule_id="syntax-check",
            category="Not A Real Category",
            severity="Major",
            confidence="likely",
            message="broken workflow",
            path=".github/workflows/broken.yml",
            start_line=2,
            end_line=2,
            fingerprint="abc",
            evidence=[],
            remediation=None,
            autofix=None,
            introduced_by_pr="unknown",
            source="analyzer",
            cluster_id=None,
        )


@pytest.mark.parametrize("confidence", ["certain", "likely", "possible"])
def test_confidence_axis_values(confidence: str) -> None:
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.Finding(
        tool="actionlint",
        rule_id="syntax-check",
        category=FINDING_CATEGORIES[0],
        severity="Major",
        confidence=confidence,
        message="broken workflow",
        path=".github/workflows/broken.yml",
        start_line=2,
        end_line=2,
        fingerprint="abc",
        evidence=[],
        remediation=None,
        autofix=None,
        introduced_by_pr="unknown",
        source="analyzer",
        cluster_id=None,
    )
    assert finding.confidence == confidence


@pytest.mark.parametrize("source", ["analyzer", "agent", "ci"])
def test_source_literal_values(source: str) -> None:
    finding_mod = import_module("mergecraft.analyzers.finding")
    finding = finding_mod.make_finding(
        tool="zizmor",
        rule_id="unpinned-uses-ref",
        category="Security & Privacy",
        severity="Major",
        confidence="likely",
        message="unpinned action",
        path=".github/workflows/unpinned-action.yml",
        start_line=11,
        end_line=11,
        source=source,
    )
    assert finding.source == source


def test_fingerprint_delegates_to_review_taxonomy_helper() -> None:
    finding_mod = import_module("mergecraft.analyzers.finding")
    body = "Using latest is prone to errors."
    expected = finding_fingerprint(path="Dockerfile", body=body)
    finding = finding_mod.make_finding(
        tool="hadolint",
        rule_id="DL3007",
        category="Maintainability & Code Quality",
        severity="Major",
        confidence="certain",
        message=body,
        path="Dockerfile",
        start_line=2,
        end_line=2,
        source="analyzer",
    )
    assert finding.fingerprint == expected


def test_invalid_effort_not_on_finding_model() -> None:
    finding_mod = import_module("mergecraft.analyzers.finding")
    fields = set(finding_mod.Finding.model_fields)
    assert "effort" not in fields
    assert FINDING_EFFORTS  # taxonomy still owns effort for agent findings
