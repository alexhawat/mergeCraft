"""OSV-Scanner JSON output parser."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
)
from mergecraft.review_taxonomy import FINDING_SEVERITIES

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_SEVERITY_RANK = {name: index for index, name in enumerate(reversed(FINDING_SEVERITIES))}


def _osv_severity(vulnerability: dict[str, Any]) -> str:
    for item in vulnerability.get("severity") or []:
        if isinstance(item, dict) and item.get("type") == "CVSS_V3":
            score = str(item.get("score") or "")
            if score.startswith(("9", "10")):
                return "critical"
            if score.startswith(("7", "8")):
                return "high"
            if score.startswith(("4", "5", "6")):
                return "medium"
            return "low"
    group_severity = vulnerability.get("max_severity")
    if group_severity is not None:
        try:
            score_value = float(group_severity)
        except TypeError, ValueError:
            score_value = 0.0
        if score_value >= 9.0:
            return "critical"
        if score_value >= 7.0:
            return "high"
        if score_value >= 4.0:
            return "medium"
        return "low"
    return "medium"


def _prefer_rule_id(vulnerability: dict[str, Any]) -> str:
    aliases = vulnerability.get("aliases") or []
    if isinstance(aliases, list):
        for alias in aliases:
            text = str(alias)
            if text.startswith("CVE-"):
                return text
        for alias in aliases:
            text = str(alias)
            if text.startswith("GHSA-"):
                return text
    rule_id = str(vulnerability.get("id") or "osv")
    if rule_id.startswith(("CVE-", "GHSA-")):
        return rule_id
    return rule_id


def _fixed_version(vulnerability: dict[str, Any]) -> str | None:
    for affected in vulnerability.get("affected") or []:
        if not isinstance(affected, dict):
            continue
        for item_range in affected.get("ranges") or []:
            if not isinstance(item_range, dict):
                continue
            if item_range.get("type") != "ECOSYSTEM":
                continue
            for event in item_range.get("events") or []:
                if isinstance(event, dict) and "fixed" in event:
                    fixed = str(event["fixed"])
                    if re.fullmatch(r"\d+\.\d+.\d+", fixed):
                        return fixed
    return None


def _severity_rank(taxonomy_severity: str) -> int:
    return _SEVERITY_RANK.get(taxonomy_severity, 0)


def parse_osv_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        msg = "osv JSON output must be an object"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for result in payload.get("results") or []:
        if not isinstance(result, dict):
            continue
        source = result.get("source") or {}
        path = resolve_repo_relative_path(str(source.get("path") or "unknown"), repo_root=repo_root)
        for package in result.get("packages") or []:
            if not isinstance(package, dict):
                continue
            pkg_info = package.get("package") or {}
            pkg_name = str(pkg_info.get("name") or "")
            for vulnerability in package.get("vulnerabilities") or []:
                if not isinstance(vulnerability, dict):
                    continue
                native_level = _osv_severity(vulnerability)
                rule_id = _prefer_rule_id(vulnerability)
                summary = str(
                    vulnerability.get("summary") or vulnerability.get("details") or rule_id
                )
                fixed = _fixed_version(vulnerability)
                remediation = f"Upgrade to {fixed} or later" if fixed else None
                findings.append(
                    make_finding(
                        tool=manifest.id,
                        rule_id=rule_id,
                        category=category,
                        severity=map_native_severity(manifest, native_level),
                        confidence=map_confidence(None),
                        message=summary,
                        path=path,
                        start_line=1,
                        end_line=1,
                        source="analyzer",
                        remediation=remediation,
                        evidence=[f"package: {pkg_name}"] if pkg_name else [],
                    )
                )
    return findings


__all__ = [
    "_fixed_version",
    "_prefer_rule_id",
    "_severity_rank",
    "parse_osv_json",
]
