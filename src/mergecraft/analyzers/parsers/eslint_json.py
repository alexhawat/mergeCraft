"""ESLint JSON output parser."""

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

_ESLINT_SEVERITY: dict[int, str] = {1: "warning", 2: "error"}


def parse_eslint_json(raw: str, *, manifest: AnalyzerManifest, repo_root: Path) -> list[Finding]:
    payload = json.loads(raw)
    if not isinstance(payload, list):
        msg = "eslint JSON output must be an array"
        raise ValueError(msg)

    category = taxonomy_category(manifest)
    findings: list[Finding] = []
    for file_result in payload:
        if not isinstance(file_result, dict):
            continue
        path = resolve_repo_relative_path(
            str(file_result.get("filePath") or ""), repo_root=repo_root
        )
        for message in file_result.get("messages") or []:
            if not isinstance(message, dict):
                continue
            severity_num = int(message.get("severity") or 1)
            native_level = _ESLINT_SEVERITY.get(severity_num, "warning")
            start_line = coerce_line(message.get("line", 1))
            end_line = coerce_line(message.get("endLine", start_line), default=start_line)
            findings.append(
                make_finding(
                    tool=manifest.id,
                    rule_id=str(message.get("ruleId") or "eslint"),
                    category=category,
                    severity=map_native_severity(manifest, native_level),
                    confidence=map_confidence(None),
                    message=str(message.get("message") or "eslint finding"),
                    path=path,
                    start_line=start_line,
                    end_line=end_line,
                    source="analyzer",
                )
            )
    return findings


__all__ = ["parse_eslint_json"]
