"""Normalized analyzer finding schema (D2)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mergecraft.review_taxonomy import (
    FINDING_CATEGORIES,
    FINDING_CONFIDENCES,
    FINDING_SEVERITIES,
    FindingSource,
    finding_fingerprint,
)

IntroducedByPr = Literal["true", "false", "unknown"]


class FindingValidationError(ValueError):
    """Raised when a finding violates taxonomy constraints."""


class Finding(BaseModel):
    """One normalized finding from an analyzer, agent, or CI source."""

    model_config = ConfigDict(extra="forbid")

    tool: str
    rule_id: str
    category: str
    severity: str
    confidence: str
    message: str
    path: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    fingerprint: str
    evidence: list[str]
    remediation: str | None
    autofix: str | None
    introduced_by_pr: IntroducedByPr
    source: FindingSource
    cluster_id: str | None

    def __init__(self, **data: object) -> None:
        try:
            super().__init__(**data)
        except ValidationError as exc:
            raise FindingValidationError(str(exc)) from exc

    @field_validator("category")
    @classmethod
    def _category_must_be_taxonomy_member(cls, value: str) -> str:
        if value not in FINDING_CATEGORIES:
            msg = f"category must be one of {FINDING_CATEGORIES!r}, got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("severity")
    @classmethod
    def _severity_must_be_taxonomy_member(cls, value: str) -> str:
        if value not in FINDING_SEVERITIES:
            msg = f"severity must be one of {FINDING_SEVERITIES!r}, got {value!r}"
            raise ValueError(msg)
        return value

    @field_validator("confidence")
    @classmethod
    def _confidence_must_be_taxonomy_member(cls, value: str) -> str:
        if value not in FINDING_CONFIDENCES:
            msg = f"confidence must be one of {FINDING_CONFIDENCES!r}, got {value!r}"
            raise ValueError(msg)
        return value


def make_finding(
    *,
    tool: str,
    rule_id: str,
    category: str,
    severity: str,
    confidence: str,
    message: str,
    path: str,
    start_line: int,
    end_line: int,
    source: FindingSource,
    evidence: list[str] | None = None,
    remediation: str | None = None,
    autofix: str | None = None,
    introduced_by_pr: IntroducedByPr = "unknown",
    cluster_id: str | None = None,
    fingerprint: str | None = None,
) -> Finding:
    """Construct a finding with taxonomy validation and fingerprint stamping."""
    body = message
    computed = fingerprint or finding_fingerprint(path=path, body=body)
    try:
        return Finding(
            tool=tool,
            rule_id=rule_id,
            category=category,
            severity=severity,
            confidence=confidence,
            message=message,
            path=path,
            start_line=start_line,
            end_line=end_line,
            fingerprint=computed,
            evidence=evidence or [],
            remediation=remediation,
            autofix=autofix,
            introduced_by_pr=introduced_by_pr,
            source=source,
            cluster_id=cluster_id,
        )
    except ValueError as exc:
        raise FindingValidationError(str(exc)) from exc


__all__ = [
    "Finding",
    "FindingValidationError",
    "IntroducedByPr",
    "make_finding",
]
