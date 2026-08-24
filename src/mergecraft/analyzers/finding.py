"""Normalized analyzer finding schema (D2).

Short finding ids (issue #452) use prefix ``MC-`` and the leading hex of
``Finding.fingerprint``. Single-fingerprint ids truncate to six hex chars
(``MC-a83f91``). ``resolve_finding_short_ids`` extends truncation within a
batch when two fingerprints would otherwise share the same six-char prefix.
"""

from __future__ import annotations

import json
import re
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
    from collections.abc import Sequence
    from pathlib import Path

STRUCTURED_OUTPUT_REQUIRED_MSG = (
    "output_schema was provided but agent did not call set_output — structured output is required"
)

FINDING_SHORT_ID_PREFIX = "MC-"
_FINDING_SHORT_ID_DEFAULT_HEX_LEN = 6
_FINGERPRINT_HEX_RE = re.compile(r"^[0-9a-f]+$")

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
    lens: str | None = None
    collateral: list[str] = Field(default_factory=list)

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
    lens: str | None = None,
    collateral: list[str] | None = None,
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
            lens=lens,
            collateral=collateral or [],
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


def _validate_fingerprint_for_short_id(fingerprint: str) -> str:
    """Reject empty, traversal, and other unsafe fingerprint values."""
    if not isinstance(fingerprint, str):
        msg = "fingerprint must be a string"
        raise TypeError(msg)
    if not fingerprint or fingerprint in {".", ".."}:
        msg = f"unsafe fingerprint value: {fingerprint!r}"
        raise ValueError(msg)
    if "/" in fingerprint or "\\" in fingerprint:
        msg = f"unsafe fingerprint value: {fingerprint!r}"
        raise ValueError(msg)
    if len(fingerprint) < _FINDING_SHORT_ID_DEFAULT_HEX_LEN:
        msg = (
            f"fingerprint must be at least {_FINDING_SHORT_ID_DEFAULT_HEX_LEN} "
            f"characters, got {len(fingerprint)}"
        )
        raise ValueError(msg)
    if not _FINGERPRINT_HEX_RE.fullmatch(fingerprint):
        msg = f"fingerprint must be lowercase hex, got {fingerprint!r}"
        raise ValueError(msg)
    return fingerprint


def finding_short_id(fingerprint: str) -> str:
    """Return the default short id for one fingerprint (six hex chars after ``MC-``)."""
    validated = _validate_fingerprint_for_short_id(fingerprint)
    return f"{FINDING_SHORT_ID_PREFIX}{validated[:_FINDING_SHORT_ID_DEFAULT_HEX_LEN]}"


def resolve_finding_short_ids(fingerprints: Sequence[str]) -> dict[str, str]:
    """Assign stable short ids, extending truncation when six-char prefixes collide."""
    validated_by_input: dict[str, str] = {}
    for fp in fingerprints:
        validated_by_input[fp] = _validate_fingerprint_for_short_id(fp)
    unique = sorted(dict.fromkeys(validated_by_input.values()))
    assigned: dict[str, str] = {}
    used_ids: set[str] = set()
    for fingerprint in unique:
        hex_len = _FINDING_SHORT_ID_DEFAULT_HEX_LEN
        while hex_len <= len(fingerprint):
            candidate = f"{FINDING_SHORT_ID_PREFIX}{fingerprint[:hex_len]}"
            if candidate not in used_ids:
                assigned[fingerprint] = candidate
                used_ids.add(candidate)
                break
            hex_len += 1
        else:
            candidate = f"{FINDING_SHORT_ID_PREFIX}{fingerprint}"
            assigned[fingerprint] = candidate
            used_ids.add(candidate)
    return {fp: assigned[validated_by_input[fp]] for fp in fingerprints}


def _finding_location(finding: Finding) -> str:
    """Return ``path:line`` when line-anchored, else ``path`` alone."""
    if finding.start_line is not None:
        return f"{finding.path}:{finding.start_line}"
    return finding.path


def render_finding_markdown(finding: Finding, *, short_id: str) -> str:
    """Render one finding as a markdown section that quotes ``short_id``."""
    location = _finding_location(finding)
    lines = [
        f"## [{short_id}] {location}",
        "",
        f"**{finding.severity}** · `{finding.tool}/{finding.rule_id}`",
        "",
        finding.message,
        "",
        f"`{short_id}` · fingerprint `{finding.fingerprint}`",
    ]
    return "\n".join(lines)


def finding_json_record(finding: Finding, *, short_id: str) -> dict[str, Any]:
    """Serialize a finding for structured JSON export with a stable short id."""
    record = finding.model_dump()
    record["short_id"] = short_id
    return record


def render_finding_pr_comment(finding: Finding, *, short_id: str) -> str:
    """Render a PR inline comment body that surfaces ``short_id`` for quoting."""
    location = _finding_location(finding)
    return f"**{short_id}** ({location})\n\n{finding.message}"


__all__ = [
    "FINDING_SHORT_ID_PREFIX",
    "STRUCTURED_OUTPUT_REQUIRED_MSG",
    "Finding",
    "FindingValidationError",
    "FindingsPayload",
    "IntroducedByPr",
    "finding_json_record",
    "finding_short_id",
    "findings_output_schema",
    "make_finding",
    "parse_findings_payload",
    "render_finding_markdown",
    "render_finding_pr_comment",
    "resolve_finding_short_ids",
    "write_findings_json",
]
