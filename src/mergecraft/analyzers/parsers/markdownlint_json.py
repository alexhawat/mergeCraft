"""markdownlint-cli ``--json`` array parser."""

from __future__ import annotations

from typing import TYPE_CHECKING

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    require_json_array,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def parse_markdownlint_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    payload = require_json_array(raw, what="markdownlint JSON output")
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        names = item.get("ruleNames")
        rule_id = "markdownlint"
        if isinstance(names, list) and names:
            rule_id = str(names[0])
        start_line = coerce_line(item.get("lineNumber", 1))
        message = str(item.get("ruleDescription") or item.get("errorDetail") or rule_id)
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, "error"),
                confidence=map_confidence(None),
                message=message,
                path=resolve_repo_relative_path(
                    str(item.get("fileName") or ""), repo_root=repo_root
                )
                or "unknown.md",
                start_line=start_line,
                end_line=start_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_markdownlint_json"]
