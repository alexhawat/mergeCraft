"""Normalized analyzer finding schema (D2)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mergecraft.review_taxonomy import (
    FINDING_CATEGORIES,
    FINDING_CONFIDENCES,
    FINDING_SEVERITIES,
    FindingSource,
    finding_fingerprint,
)

if TYPE_CHECKING:
    from pathlib import Path

STRUCTURED_OUTPUT_REQUIRED_MSG = (
    "output_schema was provided but agent did not call set_output — structured output is required"
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
    start_line: int | None = Field(default=None, ge=1)
    end_line: int | None = Field(default=None, ge=1)
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
    start_line: int | None,
    end_line: int | None,
    source: FindingSource,
    evidence: list[str] | None = None,
    remediation: str | None = None,
    autofix: str | None = None,
    introduced_by_pr: IntroducedByPr = "unknown",
    cluster_id: str | None = None,
    fingerprint: str | None = None,
) -> Finding:
    """Construct a finding with taxonomy validation and fingerprint stamping."""
    if end_line is None:
        end_line = start_line
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


class FindingsPayload(BaseModel):
    """Structured ``set_output`` envelope for benchmark/scoring workflows."""

    model_config = ConfigDict(extra="forbid")

    findings: list[Finding]


def findings_output_schema() -> dict[str, Any]:
    """JSON Schema for structured findings output derived from ``Finding``."""
    item_schema = Finding.model_json_schema()
    properties = item_schema.get("properties")
    if isinstance(properties, dict):
        properties["category"] = {"type": "string", "enum": list(FINDING_CATEGORIES)}
        properties["severity"] = {"type": "string", "enum": list(FINDING_SEVERITIES)}
        properties["confidence"] = {"type": "string", "enum": list(FINDING_CONFIDENCES)}
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": item_schema,
            }
        },
        "required": ["findings"],
    }


def parse_findings_payload(raw: str) -> list[dict[str, Any]]:
    """Parse structured output JSON and validate each finding."""
    try:
        payload = FindingsPayload.model_validate_json(raw)
    except ValidationError as exc:
        msg = f"set_output does not conform to findings schema: {exc}"
        raise ValueError(msg) from exc
    return [finding.model_dump() for finding in payload.findings]


def write_findings_json(json_path: Path, findings: list[dict[str, Any]]) -> None:
    """Write validated findings to a pretty-printed JSON file."""
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"findings": findings}, indent=2, ensure_ascii=False)
    json_path.write_text(f"{payload}\n", encoding="utf-8")


__all__ = [
    "STRUCTURED_OUTPUT_REQUIRED_MSG",
    "Finding",
    "FindingValidationError",
    "FindingsPayload",
    "IntroducedByPr",
    "findings_output_schema",
    "make_finding",
    "parse_findings_payload",
    "write_findings_json",
]
