"""Policy rule schema — strict YAML validation with stable rule IDs (DG5)."""

from __future__ import annotations

from typing import Literal, NoReturn

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from mergecraft.review_taxonomy import FINDING_SEVERITIES

EnforcementModeLiteral = Literal["advisory", "warning", "required", "blocking"]
SeverityLiteral = Literal["Critical", "Major", "Minor", "Trivial"]


class PolicyConfigError(ValueError):
    """Raised when a policy document violates the schema or carries unknown keys."""


class RuleScope(BaseModel):
    """Optional scope dimensions for a policy rule."""

    model_config = ConfigDict(extra="forbid")

    org: str | None = None
    repo: str | None = None
    branch: str | None = None
    path: str | None = None
    language: str | None = None


class RuleEvidence(BaseModel):
    """Evidence requirements attached to a policy rule (D8)."""

    model_config = ConfigDict(extra="forbid")

    required: list[str] = Field(default_factory=list)


class PolicyRule(BaseModel):
    """One versioned, schema-validated policy rule."""

    model_config = ConfigDict(extra="forbid")

    id: str
    owner: str
    version: int = Field(ge=1)
    rationale: str
    severity: SeverityLiteral
    enforcement: EnforcementModeLiteral = "advisory"
    scope: RuleScope | None = None
    evidence: RuleEvidence | None = None

    @field_validator("severity")
    @classmethod
    def _severity_must_be_taxonomy_member(cls, value: str) -> str:
        if value not in FINDING_SEVERITIES:
            msg = f"severity must be one of {FINDING_SEVERITIES!r}, got {value!r}"
            raise ValueError(msg)
        return value


def _raise_config_error(exc: ValidationError) -> NoReturn:
    message = str(exc)
    lowered = message.lower()
    if "extra" in lowered or "unexpected" in lowered:
        msg = f"unknown or unexpected key in policy rule: {message}"
        raise PolicyConfigError(msg) from exc
    msg = f"policy rule config error: {message}"
    raise PolicyConfigError(msg) from exc


def _validate_rule_data(data: object) -> PolicyRule:
    if not isinstance(data, dict):
        msg = "policy rule must be a YAML mapping"
        raise PolicyConfigError(msg)
    try:
        return PolicyRule.model_validate(data)
    except ValidationError as exc:
        _raise_config_error(exc)


def parse_rule(text: str) -> PolicyRule:
    """Parse one YAML rule document into a :class:`PolicyRule`."""
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in policy rule: {exc}"
        raise PolicyConfigError(msg) from exc
    if loaded is None:
        msg = "policy rule document is empty"
        raise PolicyConfigError(msg)
    return _validate_rule_data(loaded)


def parse_rules_document(text: str) -> list[PolicyRule]:
    """Parse a policy bundle (``rules:`` list) or a single rule document."""
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        msg = f"invalid YAML in policy document: {exc}"
        raise PolicyConfigError(msg) from exc
    if loaded is None:
        msg = "policy document is empty"
        raise PolicyConfigError(msg)
    if isinstance(loaded, dict) and "rules" in loaded:
        rules_raw = loaded["rules"]
        if not isinstance(rules_raw, list):
            msg = "policy 'rules' key must be a list"
            raise PolicyConfigError(msg)
        return [_validate_rule_data(item) for item in rules_raw]
    return [_validate_rule_data(loaded)]


__all__ = [
    "EnforcementModeLiteral",
    "PolicyConfigError",
    "PolicyRule",
    "RuleEvidence",
    "RuleScope",
    "parse_rule",
    "parse_rules_document",
]
