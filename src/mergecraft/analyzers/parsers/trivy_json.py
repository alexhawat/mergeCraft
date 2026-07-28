"""Trivy JSON output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    map_confidence,
    map_native_severity,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def parse_trivy_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    _ = repo_root
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        msg = "trivy JSON output must be an object"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for result in payload.get("Results") or []:
        if not isinstance(result, dict):
            continue
        path = str(result.get("Target") or "unknown")
        for vulnerability in result.get("Vulnerabilities") or []:
            if not isinstance(vulnerability, dict):
                continue
            native_level = str(vulnerability.get("Severity") or "unknown").casefold()
            rule_id = str(vulnerability.get("VulnerabilityID") or "trivy")
            title = str(vulnerability.get("Title") or vulnerability.get("Description") or rule_id)
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native_level),
                    confidence=map_confidence(None),
                    message=title,
                    path=path,
                    start_line=1,
                    end_line=1,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_trivy_json"]
