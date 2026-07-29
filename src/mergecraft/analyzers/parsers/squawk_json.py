"""Squawk ``--reporter=json`` output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

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


def parse_squawk_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        msg = "squawk JSON output must be an array"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        native_level = str(item.get("level") or "Warning").casefold()
        if native_level not in manifest.severity_map:
            native_level = "warning"
        rule_id = str(item.get("rule_name") or "squawk")
        message = str(item.get("message") or rule_id)
        help_text = str(item.get("help") or "")
        path = resolve_repo_relative_path(str(item.get("file") or "unknown"), repo_root=repo_root)
        line = coerce_line(item.get("line"))
        end_line = coerce_line(item.get("line_end"), default=line)
        evidence = [help_text] if help_text else []
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, native_level),
                confidence=map_confidence(None),
                message=message,
                path=path,
                start_line=line,
                end_line=end_line,
                source="analyzer",
                evidence=evidence,
                remediation=help_text or None,
                introduced_by_pr="true",
            )
        )
    return findings


__all__ = ["parse_squawk_json"]
