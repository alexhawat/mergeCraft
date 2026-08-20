"""stylelint ``--formatter json`` array parser."""

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

_LEVELS: dict[str, str] = {"error": "error", "warning": "warning"}


def parse_stylelint_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = require_json_array(raw, what="stylelint JSON output")
    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        path = resolve_repo_relative_path(
            str(file_result.get("source") or file_result.get("filePath") or ""),
            repo_root=repo_root,
        )
        warnings = file_result.get("warnings")
        if not isinstance(warnings, list):
            continue
        for warning in warnings:
            if not isinstance(warning, dict):
                continue
            native = _LEVELS.get(str(warning.get("severity") or "warning").casefold(), "warning")
            start_line = coerce_line(warning.get("line", 1))
            end_line = coerce_line(warning.get("endLine", start_line), default=start_line)
            rule_id = str(warning.get("rule") or "stylelint")
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=rule_id,
                    category=category,
                    severity=map_native_severity(manifest, native),
                    confidence=map_confidence(None),
                    message=str(warning.get("text") or rule_id),
                    path=path or "unknown.css",
                    start_line=start_line,
                    end_line=end_line,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_stylelint_json"]
