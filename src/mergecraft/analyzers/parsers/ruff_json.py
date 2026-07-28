"""Ruff JSON output parser."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def parse_ruff_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    _ = repo_root
    payload = json.loads(raw)
    if not isinstance(payload, list):
        msg = "ruff JSON output must be an array"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        path = str(item.get("filename") or "")
        location = item.get("location") or {}
        start_line = coerce_line(location.get("row", 1))
        end_line = start_line
        native_level = str(item.get("severity") or "warning")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=str(item.get("code") or "ruff"),
                category=category,
                severity=map_native_severity(manifest, native_level),
                confidence=map_confidence(None),
                message=str(item.get("message") or "ruff finding"),
                path=path,
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_ruff_json"]
