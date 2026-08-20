"""SQLFluff ``lint --format json`` output parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    map_confidence,
    map_native_severity,
    resolve_repo_relative_path,
    taxonomy_category,
    try_load_json,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest


def _file_rows(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        files = payload.get("files") or payload.get("violations")
        if isinstance(files, list):
            return [item for item in files if isinstance(item, dict)]
        if "filepath" in payload or "violations" in payload:
            return [payload]
    return []


def parse_sqlfluff_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = try_load_json(raw)
    if payload is None:
        return []

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for row in _file_rows(payload):
        path = resolve_repo_relative_path(
            str(row.get("filepath") or row.get("file") or ""), repo_root=repo_root
        )
        violations = row.get("violations")
        if not isinstance(violations, list):
            continue
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            start_line = coerce_line(violation.get("line_no", violation.get("start_line_no", 1)))
            rule_id = str(violation.get("code") or violation.get("name") or "sqlfluff")
            message = str(violation.get("description") or violation.get("name") or rule_id)
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, "warning"),
                    confidence=map_confidence(None),
                    message=message,
                    path=path or "unknown.sql",
                    start_line=start_line,
                    end_line=start_line,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_sqlfluff_json"]
