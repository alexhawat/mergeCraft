"""OSV-Scanner JSON output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    map_confidence,
    map_native_severity,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


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
    return "medium"


def parse_osv_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    _ = repo_root
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
        path = str(source.get("path") or "unknown")
        for package in result.get("packages") or []:
            if not isinstance(package, dict):
                continue
            for vulnerability in package.get("vulnerabilities") or []:
                if not isinstance(vulnerability, dict):
                    continue
                native_level = _osv_severity(vulnerability)
                rule_id = str(vulnerability.get("id") or "osv")
                summary = str(
                    vulnerability.get("summary") or vulnerability.get("details") or rule_id
                )
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
                    )
                )
    return findings


__all__ = ["parse_osv_json"]
