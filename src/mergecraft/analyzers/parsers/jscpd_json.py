"""jscpd ``--reporters json`` duplicates parser."""

from __future__ import annotations

from typing import TYPE_CHECKING

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


def _file_span(entry: object, *, repo_root: Path) -> tuple[str, int, int]:
    if not isinstance(entry, dict):
        return "", 1, 1
    path = resolve_repo_relative_path(str(entry.get("name") or ""), repo_root=repo_root)
    start = coerce_line(entry.get("start", 1))
    end = coerce_line(entry.get("end", start), default=start)
    if end < start:
        end = start
    return path, start, end


def parse_jscpd_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = require_json_object(raw, what="jscpd JSON output")

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    duplicates = payload.get("duplicates")
    if not isinstance(duplicates, list):
        return findings
    for clone in duplicates:
        if not isinstance(clone, dict):
            continue
        first_path, start, end = _file_span(clone.get("firstFile"), repo_root=repo_root)
        second_path, second_start, second_end = _file_span(
            clone.get("secondFile"), repo_root=repo_root
        )
        if not first_path:
            continue
        other = f"{second_path}:{second_start}-{second_end}" if second_path else "another file"
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id="clone",
                category=category,
                severity=map_native_severity(manifest, "warning"),
                confidence=map_confidence(None),
                message=f"duplicated block also found in {other}",
                path=first_path,
                start_line=start,
                end_line=end,
                source="analyzer",
                evidence=[other] if second_path else [],
            )
        )
    return findings


__all__ = ["parse_jscpd_json"]
