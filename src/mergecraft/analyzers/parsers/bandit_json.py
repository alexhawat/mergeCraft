"""Bandit ``--format json`` output parser."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mergecraft.analyzers.finding import Finding, make_finding
from mergecraft.analyzers.parsers._common import (
    coerce_line,
    iter_bandit_result_rows,
    map_confidence,
    map_native_severity,
    require_json_object,
    resolve_repo_relative_path,
    taxonomy_category,
)

if TYPE_CHECKING:
    from pathlib import Path

    from mergecraft.analyzers.manifest import AnalyzerManifest

_LEVELS: dict[str, str] = {
    "high": "high",
    "medium": "medium",
    "low": "low",
    "undefined": "undefined",
}


def _native_severity(result: dict[str, Any]) -> str:
    return _LEVELS.get(str(result.get("issue_severity") or "medium").casefold(), "medium")


def _end_line(result: dict[str, Any], start_line: int) -> int:
    line_range = result.get("line_range")
    if isinstance(line_range, list) and line_range:
        return coerce_line(line_range[-1], default=start_line)
    return start_line


def parse_bandit_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    # Empty stdout is a clean scan (Bandit JSON on a finding-free run). Do not
    # treat it as missing output; unparsable non-empty stdout still raises.
    if not raw.strip():
        return []
    payload = require_json_object(raw, what="bandit JSON output")
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for result in iter_bandit_result_rows(payload):
        path = resolve_repo_relative_path(str(result.get("filename") or ""), repo_root=repo_root)
        start_line = coerce_line(result.get("line_number", 1))
        rule_id = str(result.get("test_id") or result.get("test_name") or "bandit")
        findings.append(
            make_finding(
                tool=manifest.id,
                rule_id=rule_id,
                category=category,
                severity=map_native_severity(manifest, _native_severity(result)),
                confidence=map_confidence(str(result.get("issue_confidence") or "") or None),
                message=str(result.get("issue_text") or rule_id),
                path=path or "unknown.py",
                start_line=start_line,
                end_line=_end_line(result, start_line),
                source="analyzer",
            )
        )
    return findings


__all__ = ["parse_bandit_json"]
