"""SARIF 2.1.0 ingest parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _rule_level(rules: dict[str, dict[str, Any]], rule_id: str) -> str | None:
    rule = rules.get(rule_id)
    if rule is None:
        return None
    default = rule.get("defaultConfiguration") or {}
    level = default.get("level")
    return str(level) if level is not None else None


def _result_level(result: dict[str, Any], rules: dict[str, dict[str, Any]]) -> str:
    level = result.get("level")
    if level is not None:
        return str(level)
    rule_id = str(result.get("ruleId") or "")
    from_rule = _rule_level(rules, rule_id)
    if from_rule is not None:
        return from_rule
    return "warning"


def _message_text(result: dict[str, Any]) -> str:
    message = result.get("message") or {}
    if isinstance(message, dict):
        text = message.get("text") or message.get("markdown")
        if text:
            return str(text)
    return str(result.get("ruleId") or "finding")


def _parse_location(
    location: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[str, int, int]:
    physical = location.get("physicalLocation") or {}
    artifact = physical.get("artifactLocation") or {}
    uri = str(artifact.get("uri") or "")
    uri_base_id = artifact.get("uriBaseId")
    path = resolve_repo_relative_path(
        uri,
        repo_root=repo_root,
        uri_base_id=str(uri_base_id) if uri_base_id is not None else None,
    )
    region = physical.get("region") or {}
    start = coerce_line(region.get("startLine", region.get("line", 1)))
    end = coerce_line(region.get("endLine", start), default=start)
    if end < start:
        end = start
    return path, start, end


def _is_suppressed(result: dict[str, Any]) -> bool:
    suppressions = result.get("suppressions") or []
    for item in suppressions:
        if isinstance(item, dict) and item.get("kind") in {"inSource", "external"}:
            return True
    return False


def _confidence_from_result(result: dict[str, Any]) -> str:
    properties = result.get("properties") or {}
    if isinstance(properties, dict):
        for key in ("confidence", "precision", "security-severity"):
            if key in properties:
                return map_confidence(str(properties[key]))
    return map_confidence(None)


def _parse_run(
    run: dict[str, Any], *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    tool = run.get("tool") or {}
    driver = tool.get("driver") or {}
    rules_list = driver.get("rules") or []
    rules: dict[str, dict[str, Any]] = {}
    for rule in rules_list:
        if isinstance(rule, dict) and rule.get("id"):
            rules[str(rule["id"])] = rule

    findings: list[Finding] = []
    category = taxonomy_category(manifest)
    for result in run.get("results") or []:
        if not isinstance(result, dict):
            continue
        if _is_suppressed(result):
            continue
        rule_id = str(result.get("ruleId") or "unknown")
        native_level = _result_level(result, rules)
        severity = map_native_severity(manifest, native_level)
        confidence = _confidence_from_result(result)
        message = _message_text(result)
        locations = result.get("locations") or [{}]
        location = locations[0] if locations else {}
        if not isinstance(location, dict):
            location = {}
        path, start_line, end_line = _parse_location(location, repo_root=repo_root)
        evidence: list[str] = []
        fingerprints = result.get("partialFingerprints")
        if isinstance(fingerprints, dict):
            for key, value in sorted(fingerprints.items()):
                evidence.append(f"{key}={value}")

        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=severity,
                confidence=confidence,
                message=message,
                path=path,
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
                evidence=evidence,
            )
        )
    return findings


def parse_sarif(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    """Parse SARIF 2.1.0 text into normalized findings."""
    document = json.loads(raw)
    if not isinstance(document, dict):
        msg = "SARIF document must be a JSON object"
        raise ValueError(msg)
    if document.get("version") != "2.1.0":
        runs = document.get("runs")
        if not isinstance(runs, list) or not runs:
            msg = f"unsupported SARIF version: {document.get('version')!r}"
            raise ValueError(msg)

    findings: list[Finding] = []
    for run in document.get("runs") or []:
        if isinstance(run, dict):
            findings.extend(_parse_run(run, manifest=manifest, repo_root=repo_root))
    return findings


__all__ = ["parse_sarif"]
