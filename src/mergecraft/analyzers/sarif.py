"""SARIF 2.1.0 export and schema validation."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import jsonschema

if TYPE_CHECKING:
    from mergecraft.analyzers.finding import Finding

SARIF_SCHEMA_URL = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json"
)

_SEVERITY_TO_LEVEL: dict[str, str] = {
    "Critical": "error",
    "Major": "error",
    "Minor": "warning",
    "Trivial": "note",
}

_MINIMAL_SARIF_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["version", "runs"],
    "properties": {
        "version": {"const": "2.1.0"},
        "$schema": {"type": "string"},
        "runs": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["tool", "results"],
                "properties": {
                    "tool": {"type": "object"},
                    "results": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["ruleId", "level", "message", "locations"],
                        },
                    },
                },
            },
        },
    },
}


def _level_for_severity(severity: str) -> str:
    return _SEVERITY_TO_LEVEL.get(severity, "warning")


def export_sarif(findings: list[Finding]) -> dict[str, Any]:
    """Export mergeCraft findings as SARIF 2.1.0 for GitHub code scanning."""
    results: list[dict[str, Any]] = []
    rule_ids: set[str] = set()
    for finding in findings:
        rule_ids.add(finding.rule_id)
        results.append(
            {
                "ruleId": finding.rule_id,
                "level": _level_for_severity(finding.severity),
                "message": {"text": finding.message},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": finding.path},
                            "region": {
                                "startLine": finding.start_line,
                                "endLine": finding.end_line,
                            },
                        }
                    }
                ],
                "properties": {"confidence": finding.confidence, "tool": finding.tool},
            }
        )

    rules = [
        {"id": rule_id, "defaultConfiguration": {"level": "warning"}}
        for rule_id in sorted(rule_ids)
    ]
    return {
        "$schema": SARIF_SCHEMA_URL,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {"driver": {"name": "mergecraft", "rules": rules}},
                "results": results,
            }
        ],
    }


def validate_sarif_document(document: dict[str, Any]) -> None:
    """Validate a SARIF document against the 2.1.0 schema subset used in tests."""
    jsonschema.validate(instance=document, schema=_MINIMAL_SARIF_SCHEMA)


__all__ = ["SARIF_SCHEMA_URL", "export_sarif", "validate_sarif_document"]
