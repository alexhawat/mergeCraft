"""prisma-lint ``--output-format json`` parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    require_json_object,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _violations(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows = payload.get("violations")
    if not isinstance(rows, list):
        return []
    return [item for item in rows if isinstance(item, dict)]


def parse_prisma_lint_json(
    raw: str, *, manifest: AnalyzerManifest, repo_root: Path
) -> list[Finding]:
    payload = require_json_object(raw, what="prisma-lint JSON output")
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for item in _violations(payload):
        location_raw = item.get("location")
        location = location_raw if isinstance(location_raw, dict) else {}
        start_line = coerce_line(location.get("startLine", item.get("startLine", 1)))
        end_line = coerce_line(
            location.get("endLine", item.get("endLine", start_line)), default=start_line
        )
        rule_id = str(item.get("ruleName") or "prisma-lint")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, "error"),
                confidence=map_confidence(None),
                message=str(item.get("message") or rule_id),
                path=resolve_repo_relative_path(
                    str(item.get("fileName") or ""), repo_root=repo_root
                )
                or "schema.prisma",
                start_line=start_line,
                end_line=end_line,
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_prisma_lint_json"]
